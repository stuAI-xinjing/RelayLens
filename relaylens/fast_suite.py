"""Eight representative questions, selected for coverage, not calibrated IQ."""
import random
from .tasks import ordering, code_repair
from .challenges import (constrained_selection, exact_probability, relational_query,
                         context_updates, frontend_state, backend_transactions)

SUITE_VERSION = 'fast-1'


def suite(seed, rounds=1, context_records=128):
    builders = (ordering, code_repair, constrained_selection, exact_probability,
                relational_query, context_updates, frontend_state, backend_transactions)
    result = []
    for round_index in range(rounds):
        for i,builder in enumerate(builders):
            rng = random.Random(seed+round_index*7919+(i+40)*104729)
            task = builder(rng,round_index,context_records) if builder is context_updates else builder(rng,round_index)
            task.metadata['difficulty'] = 'standard' if i<2 else 'challenge'
            result.append(task)
    return result
