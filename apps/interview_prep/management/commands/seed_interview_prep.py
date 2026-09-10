"""
Seed interview preparation content.

The questions and scripts here are starting material, not a finished
library. They are written to be genuinely usable rather than to fill the
tables - a question bank of placeholders is worse than an empty one,
because nobody notices it is empty.

Idempotent: safe to re-run, updates existing rows rather than duplicating.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.interview_prep.models import (
    InterviewChecklistItem,
    InterviewQuestion,
    NegotiationScript,
    StarTemplate,
)

Q = InterviewQuestion
S = NegotiationScript
C = InterviewChecklistItem

# ---------------------------------------------------------------------------
# Questions that get asked whatever the role
# ---------------------------------------------------------------------------

GENERAL_QUESTIONS = [
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.ENTRY,
        95,
        "Tell me about yourself.",
        "Two minutes, not ten. A line on where you are now, two or three things "
        "you have done that matter for this role, and why you are in the room. "
        "Skip the chronology - they have your resume.",
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.ENTRY,
        90,
        "Why do you want to work here?",
        "Something specific about the company or the problem, not a compliment "
        "that would fit any employer. If you cannot name one thing, that is "
        "worth knowing before you accept.",
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.MID,
        85,
        "Tell me about a time you disagreed with a decision.",
        "They want to see how you disagree, not whether you were right. Show "
        "that you raised it once, clearly, and then committed - or explain "
        "honestly why you kept pushing.",
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.MID,
        80,
        "Tell me about a project that failed.",
        "Pick one that actually failed. A disguised success reads as evasion. "
        "Spend most of the answer on what you changed afterwards.",
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.MID,
        75,
        "How do you handle competing priorities?",
        "Describe the mechanism you use, not the feeling. Who you ask, what you "
        "drop, how you tell people something is slipping.",
    ),
    (
        Q.Category.SITUATIONAL,
        Q.Difficulty.MID,
        70,
        "You are halfway through a task and realise the approach is wrong. " "What do you do?",
        "The interesting part is when you speak up, not whether you fix it. "
        "Sunk cost is the trap they are testing for.",
    ),
    (
        Q.Category.CULTURE,
        Q.Difficulty.ENTRY,
        70,
        "How do you prefer to receive feedback?",
        "A real preference, with an example of feedback that landed well. "
        '"However you like" tells them nothing.',
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.SENIOR,
        65,
        "Tell me about a time you had to influence someone senior to you.",
        "Authority was not available, so what was? Data, a prototype, framing "
        "it as their problem. Say what actually moved them.",
    ),
    (
        Q.Category.BEHAVIOURAL,
        Q.Difficulty.ENTRY,
        60,
        "Why are you leaving your current role?",
        "Forward-looking and short. Criticising your current employer costs you "
        "more than the honesty gains you, even when the criticism is fair.",
    ),
    (
        Q.Category.CLOSING,
        Q.Difficulty.ENTRY,
        85,
        "Do you have any questions for us?",
        "Have three. Ask what the first ninety days look like, what makes "
        "someone succeed here, and what the team is worst at. The last one gets "
        "the most honest answer.",
    ),
    (
        Q.Category.CLOSING,
        Q.Difficulty.MID,
        60,
        "What would you want to change in your first six months?",
        "You do not know enough to answer this properly, and saying so is fine. "
        "Then describe how you would find out.",
    ),
]

# ---------------------------------------------------------------------------
# Role-specific. Keyed by TargetRole name; skipped when the role is absent.
# ---------------------------------------------------------------------------

ROLE_QUESTIONS = {
    "Senior Backend Developer": [
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            90,
            "How would you design a rate limiter for an API?",
            "Name a strategy - token bucket, sliding window - and say what it "
            "costs. Where the counter lives under multiple servers is the part "
            "they are listening for.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            85,
            "A query has become slow in production. Walk me through it.",
            "Measure before you guess. EXPLAIN, then indexes, then the query, "
            'then the schema. Jumping straight to "add an index" is the answer '
            "they hear most.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.SENIOR,
            75,
            "How do you keep a payment webhook idempotent?",
            "Store the provider event id with a unique constraint and check it "
            "before doing work. Mention the race between two identical "
            "deliveries arriving at once.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            70,
            "When would you not use a database transaction?",
            "Long-running work, external API calls inside the block, anything "
            "holding a connection while waiting on a network.",
        ),
        (
            Q.Category.SITUATIONAL,
            Q.Difficulty.SENIOR,
            65,
            "Production is down and you cannot reproduce it locally. Go.",
            "Stabilise first, diagnose second. Roll back, then read logs. "
            "Candidates who debug while the site is down are a warning sign.",
        ),
    ],
    "Senior Frontend Developer": [
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            85,
            "How do you keep a large list responsive?",
            "Virtualisation, memoisation, and knowing which one the problem "
            'actually needs. Ask what "slow" means before optimising.',
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            80,
            "How do you handle state that several distant components need?",
            "Lift it, context it, or reach for a store - and say when each stops "
            "being the right answer.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.ENTRY,
            75,
            "What makes a form accessible?",
            "Labels tied to inputs, errors announced, keyboard order that "
            "matches the visual one. Not just contrast.",
        ),
    ],
    "Data Scientist": [
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            85,
            "A metric dropped 20% overnight. How do you investigate?",
            "Check the pipeline before the business. Most overnight drops are "
            "instrumentation, not customers.",
        ),
        (
            Q.Category.SITUATIONAL,
            Q.Difficulty.MID,
            75,
            "A stakeholder wants a number you think is misleading. What do you do?",
            "Give the number and the caveat in the same sentence. Refusing "
            "outright loses the argument and the relationship.",
        ),
    ],
    "Full Stack Developer": [
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            80,
            "How do you decide what belongs on the server and what on the client?",
            "Anything involving trust, secrets or money goes server-side. The "
            "interesting answers are about the grey area - validation, and why "
            "it has to happen in both places.",
        ),
        (
            Q.Category.SITUATIONAL,
            Q.Difficulty.MID,
            70,
            "You own a feature end to end and the deadline is tight. Where do " "you cut?",
            "Full stack means you choose which layer suffers. Say which, and "
            "say what you would tell the person relying on it.",
        ),
    ],
    "DevOps Engineer": [
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            85,
            "Walk me through what happens when a deploy goes wrong at 2am.",
            "Roll back first, diagnose after. They are listening for whether "
            "you have a rollback path at all.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.SENIOR,
            75,
            "How do you decide what to alert on?",
            "Symptoms users feel, not causes. An alert nobody acts on is worse "
            "than no alert - it trains people to ignore the channel.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            70,
            "How do you handle secrets in a deployment pipeline?",
            "Never in the image, never in the repo. Say where they do live and "
            "who can read them.",
        ),
    ],
    "Product Manager": [
        (
            Q.Category.SITUATIONAL,
            Q.Difficulty.MID,
            85,
            "Engineering says a feature will take three months. The business "
            "wants it in three weeks. What do you do?",
            "Find out what the three weeks is actually for. Usually there is a "
            "smaller thing that meets the real deadline.",
        ),
        (
            Q.Category.BEHAVIOURAL,
            Q.Difficulty.MID,
            75,
            "Tell me about a feature you killed.",
            "Killing things is most of the job. Say how you knew, and how you "
            "told the people who had built it.",
        ),
    ],
    "UI/UX Designer": [
        (
            Q.Category.SITUATIONAL,
            Q.Difficulty.MID,
            80,
            "A stakeholder wants a design you think is wrong. How do you handle it?",
            "Test it rather than argue about it. Bring back what users did, not "
            "what you predicted.",
        ),
        (
            Q.Category.TECHNICAL,
            Q.Difficulty.MID,
            70,
            "How do you design for accessibility from the start?",
            "Contrast and labels are the floor. Talk about keyboard order, focus "
            "states, and what a screen reader actually announces.",
        ),
    ],
}

# ---------------------------------------------------------------------------
# STAR templates
# ---------------------------------------------------------------------------

STAR_TEMPLATES = [
    {
        "competency": "Conflict with a colleague",
        "description": "For any question about disagreement or friction.",
        "situation_prompt": "What was the disagreement about, and why did it "
        "matter to the work? Two sentences.",
        "task_prompt": "What was your responsibility here - to decide, to "
        "persuade, or to escalate?",
        "action_prompt": "What did you actually do first? Interviewers listen "
        "for whether you spoke to the person before you "
        "spoke about them.",
        "result_prompt": "What happened, and what do you do differently now? "
        "The second half is what they remember.",
        "worked_example": (
            "S: A colleague and I disagreed on whether to rewrite a service "
            "or patch it. The deadline was three weeks out.\n"
            "T: I owned the delivery date, he owned the code quality.\n"
            "A: I asked him to cost the rewrite properly rather than arguing "
            "from instinct. It came to five weeks. We patched, and I put the "
            "rewrite on the next quarter plan with his estimate attached.\n"
            "R: We shipped on time and the rewrite happened in Q3. I learned "
            "to ask for a number early instead of debating principle."
        ),
    },
    {
        "competency": "Leading without authority",
        "description": "For influence questions when you had no formal power.",
        "situation_prompt": "What needed to happen, and who could actually " "make the decision?",
        "task_prompt": "Why was it your problem despite not being your call?",
        "action_prompt": "What did you use instead of authority - evidence, "
        "a prototype, someone else's support?",
        "result_prompt": "Did they move? If not, say so and say what you " "learned.",
        "worked_example": "",
    },
    {
        "competency": "A mistake you made",
        "description": "For failure questions. The hardest one to answer well.",
        "situation_prompt": "What went wrong? Say it plainly, without " "softening.",
        "task_prompt": "What was your part in it specifically?",
        "action_prompt": "What did you do when you realised - how quickly did " "you tell someone?",
        "result_prompt": "What is different about how you work now? A lesson "
        "with no behaviour change behind it is not a lesson.",
        "worked_example": "",
    },
    {
        "competency": "Working under pressure",
        "description": "For deadline and crisis questions.",
        "situation_prompt": "What made it pressured - the timeline, the "
        "stakes, or missing information?",
        "task_prompt": "What did you own?",
        "action_prompt": "What did you cut? Everyone says they prioritised; "
        "few say what they dropped.",
        "result_prompt": "What shipped, and what was the cost of the choices " "you made?",
        "worked_example": "",
    },
]

# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------

NEGOTIATION_SCRIPTS = [
    {
        "scenario": S.Scenario.FIRST_NUMBER,
        "title": "When they ask for your number first",
        "situation": 'Early in the process, often from HR: "What are your ' 'salary expectations?"',
        "script": (
            '"I would rather understand the role properly first. Do you have '
            "a band for this position? If it helps, I am looking in the range "
            "the market pays for this level in this city, and I am flexible "
            'on structure."\n\n'
            "If they insist:\n\n"
            '"Based on what I know so far, I would be looking at X to Y. '
            "I am happy to revisit that once we have talked through the "
            'scope."'
        ),
        "tactics": [
            "Deflecting once is normal and expected. Deflecting three times " "reads as evasive.",
            "If you must give a number, give a range and make its bottom a "
            "figure you would actually accept - they will hear the bottom.",
            "Anchoring matters less than people say when the company has a "
            "fixed band, and more than they say when it does not.",
        ],
        "mistakes": [
            "Naming your current salary. In India it is asked routinely and "
            "you are not obliged to answer.",
            "Giving a range so wide it tells them nothing except that you " "have not researched.",
        ],
    },
    {
        "scenario": S.Scenario.LOWBALL,
        "title": "When the offer comes in low",
        "situation": "The offer arrives well below what you expected or what " "the market pays.",
        "script": (
            '"Thank you - I am glad you want to move forward, and I want to '
            "make this work. The number is below what I was expecting for "
            "this scope. Based on what I have seen for similar roles, I was "
            'looking at around X. Is there room to get closer to that?"\n\n'
            "Then stop talking. The silence is the tactic."
        ),
        "tactics": [
            "Say you want the job before you say the number is wrong. It "
            "changes what they hear next.",
            "Anchor to the market and the scope, not to your needs. Rent is "
            "not their problem; retention is.",
            "Ask a question at the end so the ball is with them.",
        ],
        "mistakes": [
            "Accepting on the call. Every offer can wait a day.",
            "Justifying the number with personal circumstances.",
            "Filling the silence after you ask.",
        ],
    },
    {
        "scenario": S.Scenario.COUNTER,
        "title": "Making a counter-offer",
        "situation": "You have decided the number should be higher and want "
        "to say so in writing.",
        "script": (
            '"Thanks for the offer - I am excited about the role and the '
            "team.\n\n"
            "I would like to discuss the compensation. Given [specific thing "
            "you bring that they need], I was hoping for X. If the base is "
            "fixed, I am open to discussing [joining bonus / review at six "
            "months / an extra week of leave] instead.\n\n"
            'Either way I want to make this work."'
        ),
        "tactics": [
            "One counter, not three. A second round of haggling costs " "goodwill for very little.",
            "Offering an alternative lever gives them a way to say yes when "
            "the base is genuinely fixed.",
            "Put it in writing so it can be forwarded to whoever actually " "approves it.",
        ],
        "mistakes": [
            "Threatening to walk when you would not.",
            "Negotiating before you have the written offer.",
        ],
    },
    {
        "scenario": S.Scenario.COMPETING,
        "title": "When you have a competing offer",
        "situation": "Another company has made you an offer and you would " "prefer this one.",
        "script": (
            '"I want to be straightforward with you. I have another offer at '
            "X, and I need to respond by [date]. This is the role I would "
            'rather take. Is there anything you can do on the number?"'
        ),
        "tactics": [
            "Only say it if it is true and you have it in writing. This is "
            "checked more often than people expect.",
            "Say which one you prefer. It is the part that makes them move.",
            "Give a real deadline, not an invented urgent one.",
        ],
        "mistakes": [
            "Inventing an offer. The market is smaller than it looks.",
            "Using it as leverage at a company you do not want.",
        ],
    },
    {
        "scenario": S.Scenario.NON_SALARY,
        "title": "Negotiating beyond salary",
        "situation": "The base is genuinely fixed, usually by a band or a " "level.",
        "script": (
            '"I understand the base is set at this level. Could we look at '
            "[joining bonus / an early review / remote days / learning "
            'budget / title]? Those would make a real difference to me."'
        ),
        "tactics": [
            "A joining bonus is often easier to approve than base, because "
            "it does not affect the band or anyone else's.",
            "A written six-month review is worth more than a verbal promise " "of one.",
            "Title costs them nothing and compounds for you.",
        ],
        "mistakes": [
            "Asking for everything at once. Pick two.",
            "Accepting a verbal promise about a future raise.",
        ],
    },
    {
        "scenario": S.Scenario.ACCEPTING,
        "title": "Accepting or declining",
        "situation": "The negotiation is over and you have decided.",
        "script": (
            "Accepting:\n"
            '"I am delighted to accept. Could you send the written offer with '
            'the final numbers and the start date? Looking forward to it."\n\n'
            "Declining:\n"
            '"Thank you for the offer and for the time everyone spent. I have '
            "decided to go another way. I enjoyed the conversations and hope "
            'our paths cross again."'
        ),
        "tactics": [
            "Get everything in writing before you resign anywhere.",
            "Decline warmly and briefly. You will meet these people again.",
            "Do not explain in detail why you declined unless asked.",
        ],
        "mistakes": [
            "Resigning before the written offer arrives.",
            "Going silent instead of declining. It is remembered.",
        ],
    },
]

# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------

CHECKLIST = [
    (
        C.Phase.PREPARATION,
        10,
        "Re-read the job description",
        "Pull out the three things they repeat. Those are what the interview " "will be about.",
    ),
    (
        C.Phase.PREPARATION,
        20,
        "Prepare three STAR stories",
        "One about conflict, one about a mistake, one about impact. Most "
        "behavioural questions can be answered from three good stories.",
    ),
    (
        C.Phase.PREPARATION,
        30,
        "Research the interviewers",
        "What they work on, not their life story. It shapes the questions you " "ask them.",
    ),
    (
        C.Phase.PREPARATION,
        40,
        "Write down three questions to ask",
        "Have more than you need. Two often get answered before you can ask.",
    ),
    (
        C.Phase.PREPARATION,
        50,
        "Know your number",
        "Decide your range and your walk-away figure before anyone asks. "
        "Deciding under pressure goes badly.",
    ),
    (
        C.Phase.PREPARATION,
        60,
        "Test the setup",
        "For a remote interview: camera, microphone, the actual meeting link. "
        "Do it the day before, not five minutes before.",
    ),
    (
        C.Phase.DAY_OF,
        10,
        "Re-read your own resume",
        "You will be asked about something you did four years ago and half " "forgot.",
    ),
    (
        C.Phase.DAY_OF,
        20,
        "Arrive or join five minutes early",
        "Early enough to settle, not so early that you are waiting and " "tensing up.",
    ),
    (
        C.Phase.DAY_OF,
        30,
        "Keep water and a notepad within reach",
        "Writing down a question buys you a few seconds to think.",
    ),
    (
        C.Phase.DAY_OF,
        40,
        "Ask about next steps before you leave",
        "What happens next and when. It saves a week of wondering.",
    ),
    (
        C.Phase.FOLLOW_UP,
        10,
        "Send a thank-you note within 24 hours",
        "Three sentences. Reference something specific from the conversation.",
    ),
    (
        C.Phase.FOLLOW_UP,
        20,
        "Write down what you were asked",
        "While it is fresh. The same questions come up at the next company.",
    ),
    (
        C.Phase.FOLLOW_UP,
        30,
        "Note what you would answer differently",
        "This is the part that makes the next interview better.",
    ),
    (
        C.Phase.FOLLOW_UP,
        40,
        "Follow up if the date they gave has passed",
        "One polite message. Silence usually means their process slipped, not " "that you failed.",
    ),
]


class Command(BaseCommand):
    help = "Seed interview preparation content (idempotent)"

    @transaction.atomic
    def handle(self, *args, **options):
        counts = {
            "questions": self._seed_questions(),
            "star_templates": self._seed_star(),
            "negotiation_scripts": self._seed_negotiation(),
            "checklist_items": self._seed_checklist(),
        }

        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count}")
        self.stdout.write(self.style.SUCCESS("Interview prep content seeded."))

    def _seed_questions(self):
        from apps.career_intel.models import TargetRole

        total = 0

        for category, difficulty, frequency, question, guidance in GENERAL_QUESTIONS:
            InterviewQuestion.objects.update_or_create(
                question=question,
                target_role=None,
                defaults={
                    "category": category,
                    "difficulty": difficulty,
                    "asked_frequency": frequency,
                    "guidance": guidance,
                },
            )
            total += 1

        for role_name, questions in ROLE_QUESTIONS.items():
            role = TargetRole.objects.filter(name__iexact=role_name).first()
            if role is None:
                # The role taxonomy is seeded separately and may not include
                # this one yet. Skipping is better than inventing a role.
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipped {len(questions)} questions: "
                        f'no TargetRole named "{role_name}"'
                    )
                )
                continue

            for category, difficulty, frequency, question, guidance in questions:
                InterviewQuestion.objects.update_or_create(
                    question=question,
                    target_role=role,
                    defaults={
                        "category": category,
                        "difficulty": difficulty,
                        "asked_frequency": frequency,
                        "guidance": guidance,
                    },
                )
                total += 1

        return total

    def _seed_star(self):
        for template in STAR_TEMPLATES:
            StarTemplate.objects.update_or_create(
                competency=template["competency"],
                defaults={k: v for k, v in template.items() if k != "competency"},
            )
        return len(STAR_TEMPLATES)

    def _seed_negotiation(self):
        for script in NEGOTIATION_SCRIPTS:
            NegotiationScript.objects.update_or_create(
                scenario=script["scenario"],
                defaults={k: v for k, v in script.items() if k != "scenario"},
            )
        return len(NEGOTIATION_SCRIPTS)

    def _seed_checklist(self):
        for phase, order, text, detail in CHECKLIST:
            InterviewChecklistItem.objects.update_or_create(
                phase=phase,
                text=text,
                defaults={"order": order, "detail": detail},
            )
        return len(CHECKLIST)
