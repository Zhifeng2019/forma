"""Resolve product-facing presentation without changing persisted AppSpec defaults."""

from dataclasses import dataclass
import re

from .contract import EntityContract
from .types import AppSpec


@dataclass(frozen=True)
class ResolvedPresentation:
    headline: str
    entity_label: str
    entity_plural_label: str
    collection_heading: str
    create_label: str
    delete_label: str
    empty_title: str
    empty_message: str
    created_message: str
    deleted_message: str


def _humanize(value: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', value).replace('_', ' ').replace('-', ' ').lower()


def _capitalize(value: str) -> str:
    return value[:1].upper() + value[1:]


def _pluralize(value: str) -> str:
    words = value.split()
    last = words[-1]
    if last.endswith('y') and last[-2:-1] not in 'aeiou':
        words[-1] = f'{last[:-1]}ies'
    elif last.endswith(('s', 'x', 'ch', 'sh')):
        words[-1] = f'{last}es'
    else:
        words[-1] = f'{last}s'
    return ' '.join(words)


def resolve_presentation(spec: AppSpec, contract: EntityContract) -> ResolvedPresentation:
    """Use explicit presentation when supplied and deterministic labels otherwise."""
    custom = spec.frontend.presentation
    entity_label = (custom.entity_label if custom and custom.entity_label else _humanize(contract.entity.name))
    plural_label = (
        custom.entity_plural_label if custom and custom.entity_plural_label
        else _pluralize(entity_label)
    )
    return ResolvedPresentation(
        headline=custom.headline if custom and custom.headline else spec.product.name,
        entity_label=entity_label,
        entity_plural_label=plural_label,
        collection_heading=_capitalize(plural_label),
        create_label=custom.create_label if custom and custom.create_label else f'Create {entity_label}',
        delete_label=f'Delete {entity_label}',
        empty_title=custom.empty_title if custom and custom.empty_title else f'No {plural_label} yet',
        empty_message=(
            custom.empty_message if custom and custom.empty_message
            else f'Create your first {entity_label} to get started.'
        ),
        created_message=f'{_capitalize(entity_label)} created.',
        deleted_message=f'{_capitalize(entity_label)} deleted.',
    )
