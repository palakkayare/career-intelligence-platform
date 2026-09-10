"""
Find and merge duplicate skills.

Suggests rather than decides by default. Normalising "Node.js" and "NodeJS"
to the same key is safe; normalising "C" and "C#" is not, and no rule set
should be trusted to tell the difference without a person looking.

    python manage.py merge_duplicate_skills            # list candidates
    python manage.py merge_duplicate_skills --apply    # merge them
    python manage.py merge_duplicate_skills --source X --target Y
"""
from django.core.management.base import BaseCommand, CommandError

from apps.skills.models import Skill
from apps.skills.services import SkillMergeService


class Command(BaseCommand):
    help = 'Find duplicate skills, and merge them with --apply'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually merge. Without it, only the candidates are listed.',
        )
        parser.add_argument('--source', help='Merge this skill name away')
        parser.add_argument('--target', help='...into this one')

    def handle(self, *args, **options):
        if options['source'] or options['target']:
            return self._merge_one(options['source'], options['target'])

        duplicates = SkillMergeService.find_likely_duplicates()

        if not duplicates:
            self.stdout.write(self.style.SUCCESS('No duplicate skills found.'))
            return

        self.stdout.write(f'{len(duplicates)} possible duplicate group(s):\n')

        for group in duplicates:
            names = [s.name for s in group['skills']]
            self.stdout.write(f'  {" / ".join(names)}')

            if options['apply']:
                # The most-used row wins, so the merge moves fewer
                # references and the surviving name is the one people
                # actually type.
                ranked = sorted(
                    group['skills'],
                    key=lambda s: s.seeker_skills.count(),
                    reverse=True,
                )
                target, sources = ranked[0], ranked[1:]

                for source in sources:
                    result = SkillMergeService.merge(source, target)
                    self.stdout.write(
                        f'    merged "{result["source"]}" into '
                        f'"{result["target"]}" {result["moved"]}'
                    )

        if not options['apply']:
            self.stdout.write(
                '\nRun with --apply to merge, or use --source/--target '
                'to do one pair.'
            )
            self.stdout.write(
                self.style.WARNING(
                    'Check the list first. "C" and "C#" normalise the same '
                    'way and are not duplicates.'
                )
            )

    def _merge_one(self, source_name, target_name):
        if not (source_name and target_name):
            raise CommandError('--source and --target must be used together.')

        source = Skill.objects.filter(name__iexact=source_name).first()
        target = Skill.objects.filter(name__iexact=target_name).first()

        if source is None:
            raise CommandError(f'No skill named "{source_name}".')
        if target is None:
            raise CommandError(f'No skill named "{target_name}".')

        result = SkillMergeService.merge(source, target)
        self.stdout.write(self.style.SUCCESS(
            f'Merged "{result["source"]}" into "{result["target"]}": '
            f'{result["moved"]}'
        ))