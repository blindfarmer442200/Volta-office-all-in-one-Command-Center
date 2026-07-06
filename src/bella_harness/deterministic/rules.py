"""Pattern-based rules used by the deterministic engine.

Rules are intentionally simple (regex / keyword matching) so that they are
auditable, fast, and require no model inference. Each BLOCK rule maps to one
of the categories probed by the red-team suite in redteam/probes/.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Severity ranks how dangerous a matched technique is if it were to reach the
# model. It carries no control-flow weight -- every BLOCK_RULES match blocks
# regardless of severity -- it is metadata for reporting, triage, and tests.
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"

VALID_SEVERITIES = frozenset({SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM})


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern
    description: str
    severity: str = SEVERITY_HIGH

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"invalid severity {self.severity!r} for rule {self.category!r}")


def _compile(patterns: list[str], extra_flags: int = 0) -> re.Pattern:
    return re.compile("|".join(patterns), re.IGNORECASE | extra_flags)


# --- Prompt injection: attempts to override or ignore prior instructions ---
PROMPT_INJECTION = Rule(
    category="prompt_injection",
    pattern=_compile([
        r"ignore (all |any |the )?(previous|prior|above|preceding) instructions",
        r"disregard (all |any |the )?(previous|prior|above|preceding) (instructions|prompt|rules)",
        r"forget (all |any |the )?(previous|prior|above) (instructions|context|rules)",
        r"new instructions?:",
        r"system\s*:\s*override",
        r"\bact as (system|the system|a system)\b",
        r"reveal (your |the )?(system prompt|hidden prompt|instructions)",
        r"print (your |the )?(system prompt|instructions) verbatim",
        r"repeat (the|your) (words|instructions) above",
    ]),
    description="Attempts to override, reveal, or discard prior system instructions.",
    severity=SEVERITY_CRITICAL,
)

# --- Jailbreak: known jailbreak personas / framing ---
JAILBREAK = Rule(
    category="jailbreak",
    pattern=_compile([
        r"\bdan\b.{0,20}(mode|prompt)",
        r"do anything now",
        r"you are (now )?(unrestricted|uncensored|unfiltered|jailbroken)",
        r"no (restrictions|guardrails|rules|limits) apply",
        r"pretend (you have|there are) no (content policy|guidelines|restrictions)",
        r"hypothetically\b.{0,40}?\bno (rules|restrictions|limits)\b",
        # "developer mode" only in an enabling/asserting context -- so that
        # benign queries like "what is developer mode in Chrome" aren't blocked.
        r"(enable|activate|enter|turn on|switch to) developer mode",
        r"you are (now )?in developer mode",
        r"in developer mode now",
        r"opposite day",
        r"answer as (evil|unrestricted|amoral)",
        r"an ai with no (ethical )?(guidelines|restrictions)",
        r"do not refuse (this|any) request",
        r"not allowed to (say|respond with) .{0,15}i can'?t",
        r"never (respond with|give) a refusal",
        r"must always comply\b.{0,20}(no matter|regardless)",
    ]),
    description="Known jailbreak personas or framings intended to bypass safety policy.",
    severity=SEVERITY_CRITICAL,
)

# --- Role escalation: attempts to claim elevated privilege ---
ROLE_ESCALATION = Rule(
    category="role_escalation",
    pattern=_compile([
        r"i am (the |your )?(admin|administrator|root|developer|owner) (of )?(this system|you)",
        # An "as an admin"-style claim only escalates when paired with a demand
        # to bypass/override the assistant -- otherwise it's benign context
        # ("as an admin of a Facebook group, how do I ...").
        r"as (an|the) (admin|administrator|root)( user)?\b[^.]{0,50}\b(bypass|override|ignore|disable|comply|obey|grant|unrestricted)\b",
        r"(grant|give) (me )?(admin|root|sudo|superuser) access",
        r"(enable|switch (into|to)|turn on) (debug|developer|maintenance) mode",
        r"i have (root|admin|sudo) privileges",
        r"you must (obey|comply with) (me|this) (because|since) i (am|have)",
        r"override (safety|security) (settings|checks) for (admin|root)",
    ]),
    description="Attempts to claim elevated privileges to bypass safety policy.",
    severity=SEVERITY_CRITICAL,
)

# --- Data exfiltration: requests for the ASSISTANT'S secrets/config/credentials ---
# Tightened to require a "self/system" target so benign developer questions
# ("how do I read os.environ in Python", "print environment variables in bash")
# are not blocked, while requests aimed at the assistant's own secrets are.
DATA_EXFILTRATION = Rule(
    category="data_exfiltration",
    pattern=_compile([
        # Note: extraction of the *system prompt/configuration itself* is owned
        # by the SYSTEM_PROMPT_LEAK rule; this rule targets secrets/credentials.
        r"(your|this (system|assistant|model)'?s?)\b.{0,12}\b(api keys?|secrets?|credentials?)\b",
        r"what('?s| is) your (api key|secret)\b",
        r"(print|show|dump|reveal|list|output|give|send|tell)\b.{0,50}\b(api keys?|secrets?|credentials?)\b.{0,35}\b(you|your|currently|loaded|configur\w*|access|this system|stored|used to)\b",
        r"(print|show|dump|reveal|list|output)\b.{0,40}\benv(ironment)? variables?\b.{0,25}\b(you|your|access|loaded|configur\w*|this system)\b",
        r"os\.environ\b.{0,40}\b(you|your|configur\w*|secret|api key|this system)\b",
        r"cat\s+\.env\b",
    ]),
    description="Requests to exfiltrate the assistant's secrets, credentials, or internal configuration.",
    severity=SEVERITY_CRITICAL,
)

# --- Multilingual injection: injection phrasing repeated in other languages ---
MULTILINGUAL_INJECTION = Rule(
    category="multilingual_injection",
    pattern=_compile([
        r"ignora (las )?instrucciones (anteriores|previas)",  # Spanish
        r"ignore[sz] (les )?instructions précédentes",  # French
        r"ignorieren sie (die )?vorherigen anweisungen",  # German
        r"忽略(之前|上面|前面)的(指令|指示|说明)",  # Chinese
        r"以前の指示を無視",  # Japanese
        r"проигнорируй (предыдущие|все) инструкции",  # Russian
        r"تجاهل التعليمات السابقة",  # Arabic
    ]),
    description="Prompt-injection phrasing translated into non-English languages.",
    severity=SEVERITY_HIGH,
)

# --- Structural injection: fake delimiters/turns used to smuggle a new "system" message ---
STRUCTURAL_INJECTION = Rule(
    category="structural_injection",
    pattern=_compile([
        r"\[\s*system\s*\]",
        r"<<\s*sys\s*>>",
        r"```\s*system",
        r"###\s*(instruction|system)\s*:",
        r"---\s*begin (system )?prompt\s*---",
        r"<\|?system\|?>",
        r"^\s*system\s*:\s*you (are|must|will)",
        r"<!--.*?(ignore|system|override).*?-->",
        r"\buser\s*:.*\bassistant\s*:\s*(sure|okay|understood)",
    ], extra_flags=re.DOTALL),
    description="Fake delimiters or conversation turns used to smuggle an unauthorized system message.",
    severity=SEVERITY_HIGH,
)

# --- Persona hijack: redefining the assistant's identity/rules wholesale ---
PERSONA_HIJACK = Rule(
    category="persona_hijack",
    pattern=_compile([
        r"from now on,? you are",
        r"your new persona is",
        r"roleplay as .{0,30}(no rules|no restrictions|no filter)",
        r"you (will|shall) now respond as",
        r"assume the (identity|persona|character) of .{0,40}with no (restrictions|filter)",
    ]),
    description="Attempts to wholesale-replace the assistant's identity and safety policy.",
    severity=SEVERITY_HIGH,
)

# --- Authority impersonation: claiming to be the vendor/creator to force compliance ---
AUTHORITY_IMPERSONATION = Rule(
    category="authority_impersonation",
    pattern=_compile([
        r"this is (anthropic|openai) (support|staff|engineering)",
        r"as your (creator|maker|developer),? i (command|order|require) you",
        r"i work for (anthropic|openai) and (need|require) you to",
        r"official (override|maintenance) code[: ]",
        r"authorized by (anthropic|openai) to bypass",
    ]),
    description="Claims of vendor/creator authority used to compel policy violations.",
    severity=SEVERITY_HIGH,
)

# --- System prompt leak: extracting the hidden system prompt verbatim ---
SYSTEM_PROMPT_LEAK = Rule(
    category="system_prompt_leak",
    pattern=_compile([
        r"repeat everything above this line",
        r"output your (instructions|system prompt)\b.{0,20}\b(between|inside|wrapped in)\b.{0,20}\btags\b",
        r"what (were|are) you told before this (conversation|message)",
        r"show me the (text|prompt) that comes before my (message|question)",
        r"summarize your (configuration|system prompt) in detail",
    ]),
    description="Attempts to extract the hidden system prompt verbatim or by summary.",
    severity=SEVERITY_HIGH,
)

# --- Prompt leak via translation: asking for the system prompt in another language/format ---
PROMPT_LEAK_VIA_TRANSLATION = Rule(
    category="prompt_leak_via_translation",
    pattern=_compile([
        r"translate your (system prompt|instructions) into",
        r"print your instructions in (spanish|french|german|japanese|chinese)",
        r"restate your (hidden )?instructions? as a\b.{0,10}\b(poem|song|haiku|story)",
        r"encode your system prompt in base64",
    ]),
    description="Attempts to exfiltrate the system prompt via translation or reformatting.",
    severity=SEVERITY_MEDIUM,
)

# --- Trust escalation: multi-turn grooming before a final privilege-escalation ask ---
TRUST_ESCALATION = Rule(
    category="trust_escalation",
    pattern=_compile([
        r"now that we('ve| have) built trust",
        r"since we're friends now",
        r"you('ve| have) already agreed to",
        r"as established earlier,? you agreed",
        r"we're past the rules stage",
        r"you already broke character once",
    ]),
    description="Multi-turn social-engineering framing used to leverage prior (fabricated) agreement.",
    severity=SEVERITY_MEDIUM,
)

BLOCK_RULES: list[Rule] = [
    PROMPT_INJECTION,
    JAILBREAK,
    ROLE_ESCALATION,
    DATA_EXFILTRATION,
    MULTILINGUAL_INJECTION,
    STRUCTURAL_INJECTION,
    PERSONA_HIJACK,
    AUTHORITY_IMPERSONATION,
    SYSTEM_PROMPT_LEAK,
    PROMPT_LEAK_VIA_TRANSLATION,
    TRUST_ESCALATION,
]

# ---------------------------------------------------------------------------
# Output rules: applied to the MODEL'S RESPONSE, not the user's input.
#
# These deterministically catch concrete leakage in a generated answer -- a
# credential/secret the model surfaced, or (via a configured canary) the system
# prompt itself. They complement, not replace, the model's own alignment: they
# catch specific exfiltration, not "harmful content" in general.
# ---------------------------------------------------------------------------

SECRET_IN_OUTPUT = Rule(
    category="secret_in_output",
    pattern=_compile([
        r"sk-[A-Za-z0-9]{20,}",                       # OpenAI-style secret key
        r"\bAKIA[0-9A-Z]{16}\b",                      # AWS access key id
        r"\bASIA[0-9A-Z]{16}\b",                      # AWS temporary access key id
        r"\bghp_[A-Za-z0-9]{20,}\b",                  # GitHub personal access token
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",          # GitHub fine-grained PAT
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",          # Slack token
        r"\bAIza[0-9A-Za-z\-_]{35}\b",                # Google API key
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",  # private key block
    ]),
    description="Model response contains something that looks like a leaked credential or private key.",
    severity=SEVERITY_CRITICAL,
)

OUTPUT_BLOCK_RULES: list[Rule] = [
    SECRET_IN_OUTPUT,
]

# --- Deterministic answerables: things the engine can resolve with no LLM ---
GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening))[!.\s]*$", re.IGNORECASE)
SIMPLE_ARITHMETIC = re.compile(r"^\s*[-+]?\d+(\.\d+)?\s*[-+*/]\s*[-+]?\d+(\.\d+)?\s*=?\s*$")
