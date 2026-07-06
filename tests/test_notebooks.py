import json

import pytest

from seshat.watcher.notebooks import (
    NotebookParseError,
    cells_from_json,
    cells_to_json,
    diff_notebooks,
    parse_notebook,
)


def nb_json(*cells: dict) -> str:
    return json.dumps({"cells": list(cells), "nbformat": 4, "nbformat_minor": 5})


def code_cell(source: str, cell_id: str | None = None, execution_count: int | None = None,
              outputs: list | None = None) -> dict:
    cell = {
        "cell_type": "code",
        "source": source,
        "execution_count": execution_count,
        "outputs": outputs or [],
        "metadata": {},
    }
    if cell_id:
        cell["id"] = cell_id
    return cell


def parse(*cells: dict):
    return parse_notebook(nb_json(*cells))


def test_parse_rejects_non_notebooks():
    with pytest.raises(NotebookParseError):
        parse_notebook("not json at all")
    with pytest.raises(NotebookParseError):
        parse_notebook('{"no_cells": true}')


def test_source_list_form_joined():
    cells = parse(code_cell(["import pandas\n", "print(1)"], cell_id="a"))
    assert cells[0].source == "import pandas\nprint(1)"


def test_added_cell_detected_with_outputs():
    old = parse(code_cell("import pandas", cell_id="a"))
    new = parse(
        code_cell("import pandas", cell_id="a"),
        code_cell(
            "model.fit(X, y)",
            cell_id="b",
            execution_count=2,
            outputs=[{"output_type": "stream", "name": "stdout", "text": "F1: 0.68\n"}],
        ),
    )
    diff = diff_notebooks(old, new)
    assert len(diff["added"]) == 1
    assert diff["added"][0]["id"] == "b"
    assert diff["added"][0]["outputs"] == ["F1: 0.68\n"]
    assert not diff["removed"] and not diff["modified"]


def test_modified_cell_matched_by_id_keeps_old_source():
    old = parse(code_cell("clf = RandomForest()", cell_id="a"))
    new = parse(code_cell("clf = XGBClassifier()", cell_id="a"))
    diff = diff_notebooks(old, new)
    assert len(diff["modified"]) == 1
    assert diff["modified"][0]["old_source"] == "clf = RandomForest()"
    assert diff["modified"][0]["source"] == "clf = XGBClassifier()"
    assert not diff["added"] and not diff["removed"]


def test_removed_cell_detected():
    old = parse(code_cell("a = 1", cell_id="a"), code_cell("b = 2", cell_id="b"))
    new = parse(code_cell("a = 1", cell_id="a"))
    diff = diff_notebooks(old, new)
    assert [c["id"] for c in diff["removed"]] == ["b"]


def test_reorder_detected_without_spurious_changes():
    a, b = code_cell("a = 1", cell_id="a"), code_cell("b = 2", cell_id="b")
    diff = diff_notebooks(parse(a, b), parse(b, a))
    assert diff["reordered"] is True
    assert not diff["added"] and not diff["removed"] and not diff["modified"]


def test_idless_edit_pairs_as_modification():
    old = parse(code_cell("model = XGBClassifier(max_depth=3)\nmodel.fit(X, y)"))
    new = parse(code_cell("model = XGBClassifier(max_depth=6)\nmodel.fit(X, y)"))
    diff = diff_notebooks(old, new)
    assert len(diff["modified"]) == 1
    assert not diff["added"] and not diff["removed"]


def test_idless_reorder_not_reported_as_edit():
    a, b = code_cell("a = 1"), code_cell("b = 2")
    diff = diff_notebooks(parse(a, b), parse(b, a))
    assert diff["reordered"] is True
    assert not diff["modified"]


def test_kernel_restart_heuristic():
    old = parse(code_cell("x", cell_id="a", execution_count=47))
    new = parse(code_cell("x2", cell_id="a", execution_count=2))
    assert diff_notebooks(old, new)["kernel_restarted"] is True


def test_no_change_returns_none():
    cells = [code_cell("a = 1", cell_id="a")]
    assert diff_notebooks(parse(*cells), parse(*cells)) is None


def test_long_stream_output_truncated():
    outputs = [{"output_type": "stream", "name": "stdout", "text": "epoch\n" * 5000}]
    cells = parse(code_cell("train()", cell_id="a", outputs=outputs))
    assert len(cells[0].outputs[0]) < 3000
    assert "truncated" in cells[0].outputs[0]


def test_image_output_becomes_placeholder():
    outputs = [{"output_type": "display_data", "data": {"image/png": "iVBOR..."}}]
    cells = parse(code_cell("plt.plot(x)", cell_id="a", outputs=outputs))
    assert cells[0].outputs == ["[image output]"]


def test_error_output_summarized():
    outputs = [{
        "output_type": "error",
        "ename": "ValueError",
        "evalue": "Found input variables with inconsistent numbers of samples",
        "traceback": ["line1", "line2", "line3", "line4", "line5"],
    }]
    cells = parse(code_cell("model.fit(X, y)", cell_id="a", outputs=outputs))
    out = cells[0].outputs[0]
    assert out.startswith("Error: ValueError")
    assert "line5" in out and "line1" not in out


def test_snapshot_json_roundtrip():
    cells = parse(
        code_cell("a = 1", cell_id="a", execution_count=1,
                  outputs=[{"output_type": "stream", "name": "stdout", "text": "hi"}])
    )
    assert cells_from_json(cells_to_json(cells)) == cells
