"""
Interview preparation content.

Almost all of this is curated reference material rather than user data, so
the models are shaped for editors: an admin adds a question, a tip or a
script, and it appears. The one exception is checklist progress, because a
checklist you cannot tick is just a list.

Questions hang off TargetRole rather than a free-text role name. The role
taxonomy already exists and is already used for skill gaps and career paths -
a second, unlinked set of role strings would drift from it within a month.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class InterviewQuestion(TimestampedModel):
    """A question a candidate is likely to be asked."""

    class Category(models.TextChoices):
        BEHAVIOURAL = 'behavioural', 'Behavioural'
        TECHNICAL = 'technical', 'Technical'
        SITUATIONAL = 'situational', 'Situational'
        CULTURE = 'culture', 'Culture Fit'
        CLOSING = 'closing', 'Questions To Ask Them'

    class Difficulty(models.TextChoices):
        ENTRY = 'entry', 'Entry'
        MID = 'mid', 'Mid'
        SENIOR = 'senior', 'Senior'

    # Null means the question applies to any role - "tell me about yourself"
    # is not specific to backend engineering.
    target_role = models.ForeignKey(
        'career_intel.TargetRole',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='interview_questions',
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    difficulty = models.CharField(
        max_length=10, choices=Difficulty.choices, default=Difficulty.MID,
    )

    question = models.TextField(max_length=500)
    # What a good answer covers, not a script to memorise. A recited answer
    # is worse than a hesitant honest one.
    guidance = models.TextField(
        max_length=1000, blank=True,
        help_text='What a strong answer covers. Not a model answer.',
    )
    asked_frequency = models.PositiveSmallIntegerField(
        default=50,
        help_text='0-100. Higher means more commonly asked; drives ordering.',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'interview_questions'
        ordering = ['-asked_frequency', 'id']
        indexes = [
            models.Index(fields=['target_role', 'category']),
            models.Index(fields=['category', '-asked_frequency']),
        ]

    def __str__(self):
        role = self.target_role.name if self.target_role_id else 'General'
        return f'[{role}] {self.question[:60]}'


class StarTemplate(TimestampedModel):
    """
    A STAR scaffold for one competency.

    Stored as four separate prompts rather than one block of prose so a
    frontend can render them as four fields the candidate fills in. That is
    the difference between a template and an article about templates.
    """
    competency = models.CharField(
        max_length=100, unique=True,
        help_text='e.g. Conflict resolution, Leading without authority',
    )
    description = models.CharField(max_length=300, blank=True)

    situation_prompt = models.TextField(max_length=400)
    task_prompt = models.TextField(max_length=400)
    action_prompt = models.TextField(max_length=400)
    result_prompt = models.TextField(max_length=400)

    worked_example = models.TextField(max_length=1500, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'star_templates'
        ordering = ['competency']

    def __str__(self):
        return self.competency


class CompanyInterviewTip(TimestampedModel):
    """
    Curated notes on one company's process.

    Editorial content, not user-submitted. Crowd-sourced interview intel
    invites made-up questions and score-settling, and there is no way to
    verify either.
    """

    class Category(models.TextChoices):
        PROCESS = 'process', 'Process & Rounds'
        WHAT_THEY_LOOK_FOR = 'looks_for', 'What They Look For'
        PREPARATION = 'preparation', 'How To Prepare'
        LOGISTICS = 'logistics', 'Logistics'

    company = models.ForeignKey(
        'recruiters.Company',
        on_delete=models.CASCADE,
        related_name='interview_tips',
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    tip = models.TextField(max_length=800)
    source = models.CharField(
        max_length=200, blank=True,
        help_text='Where this came from. Unsourced tips are rumour.',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'company_interview_tips'
        ordering = ['company', 'category']
        indexes = [
            models.Index(fields=['company', 'category']),
        ]

    def __str__(self):
        return f'{self.company.name}: {self.get_category_display()}'


class NegotiationScript(TimestampedModel):
    """
    What to say in one negotiation situation.

    Scripts are wording; tactics are the reasoning behind it. Both are
    stored because someone who only memorises the words falls apart the
    moment the conversation goes off-script.
    """

    class Scenario(models.TextChoices):
        FIRST_NUMBER = 'first_number', 'Asked For Your Number First'
        LOWBALL = 'lowball', 'Offer Below Expectation'
        COUNTER = 'counter', 'Making A Counter-Offer'
        COMPETING = 'competing', 'You Have A Competing Offer'
        NON_SALARY = 'non_salary', 'Negotiating Beyond Salary'
        ACCEPTING = 'accepting', 'Accepting Or Declining'

    scenario = models.CharField(
        max_length=20, choices=Scenario.choices, unique=True,
    )
    title = models.CharField(max_length=150)
    situation = models.TextField(max_length=500)
    script = models.TextField(
        max_length=1500,
        help_text='Suggested wording. Meant to be adapted, not recited.',
    )
    tactics = models.JSONField(
        default=list, blank=True,
        help_text='The reasoning behind the wording, as a list of points.',
    )
    mistakes = models.JSONField(
        default=list, blank=True,
        help_text='Common ways this conversation goes wrong.',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'negotiation_scripts'
        ordering = ['scenario']

    def __str__(self):
        return self.title


class InterviewChecklistItem(TimestampedModel):
    """One thing to do before, during or after an interview."""

    class Phase(models.TextChoices):
        PREPARATION = 'preparation', 'Before The Interview'
        DAY_OF = 'day_of', 'On The Day'
        FOLLOW_UP = 'follow_up', 'Afterwards'

    phase = models.CharField(max_length=20, choices=Phase.choices)
    text = models.CharField(max_length=300)
    detail = models.TextField(max_length=600, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'interview_checklist_items'
        ordering = ['phase', 'order', 'id']

    def __str__(self):
        return f'[{self.get_phase_display()}] {self.text[:50]}'


class ChecklistProgress(TimestampedModel):
    """
    A seeker ticking off a checklist item for one interview.

    Keyed on a free-text label rather than an Application FK on purpose:
    people prepare for interviews the platform does not know about, and a
    checklist that only works for tracked applications would be useless
    exactly when it is needed most.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='checklist_progress',
    )
    item = models.ForeignKey(
        InterviewChecklistItem,
        on_delete=models.CASCADE,
        related_name='progress',
    )
    interview_label = models.CharField(
        max_length=150,
        help_text='Which interview this is for, e.g. "Test Corp - round 2".',
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'checklist_progress'
        ordering = ['-completed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'item', 'interview_label'],
                name='one_tick_per_item_per_interview',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'interview_label']),
        ]

    def __str__(self):
        return f'{self.user.email} · {self.interview_label} · {self.item_id}'
