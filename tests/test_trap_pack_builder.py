import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location('build_trap_pack', Path(__file__).resolve().parents[1] / 'scripts' / 'build_trap_pack.py')
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def test_pack_has_twenty_per_class_and_known_expectations():
    items = builder.build(1234, 'practice')
    counts = {c: sum(1 for i in items if i['class'] == c) for c in builder.CLASSES}
    assert counts == {c: 20 for c in builder.CLASSES}
    assert all(i['expect'] == ('candidate' if i['class'].startswith('T') else 'no_candidate') for i in items)
    assert all(i['group'] == ('trap' if i['class'].startswith('T') else 'control') for i in items)


def test_same_seed_reproduces_and_other_seed_differs():
    assert builder.build(5, 'practice') == builder.build(5, 'practice')
    assert builder.build(5, 'practice') != builder.build(6, 'practice')


def test_subject_swap_figure_is_not_on_the_attributed_holder_line():
    for item in builder.build(77, 'practice'):
        if item['class'] != 'T1':
            continue
        attributed = item['sentence'].split(' 在 ')[0]
        wan = float(item['sentence'].split('约 ')[1].split(' 万股')[0].replace(',', ''))
        own = [line for line in item['sources'][0]['text'].split('\n') if attributed in line]
        assert len(own) == 1
        shares = [int(x.replace(',', '')) for x in re.findall(r'\d{1,3}(?:,\d{3})+', own[0])]
        assert all(abs(v - wan * 10_000) > 5_000 for v in shares)
