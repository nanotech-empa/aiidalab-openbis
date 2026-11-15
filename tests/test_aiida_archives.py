"""Exercise archive splitting on real AiiDA graphs, in an isolated test DB."""

from io import BytesIO

import pytest
from aiida import orm
from aiida.common.links import LinkType
from aiida.tools.archive import create_archive

from src import aiida_archives as archives


@pytest.fixture
def three_roots(aiida_profile_clean, tmp_path):
    shared = orm.Dict(dict={"shared": True}).store()
    roots = []
    children = []
    outputs = []
    for index in range(3):
        root = orm.WorkChainNode()
        root.label = f"Root {index}"
        root.set_process_label("TestWorkChain")
        root.base.links.add_incoming(shared, LinkType.INPUT_WORK, "parameters")
        if outputs:
            root.base.links.add_incoming(outputs[-1], LinkType.INPUT_WORK, "previous")
        root.store()
        calc = orm.CalcJobNode()
        calc.base.links.add_incoming(root, LinkType.CALL_CALC, "calculation")
        calc.base.links.add_incoming(shared, LinkType.INPUT_CALC, "parameters")
        calc.store()
        output = orm.SinglefileData(
            file=BytesIO(f"result {index}".encode()), filename="result.txt"
        )
        output.base.links.add_incoming(calc, LinkType.CREATE, "result")
        output.store()
        output.base.links.add_incoming(root, LinkType.RETURN, "result")
        for process in (calc, root):
            process.set_process_state("finished")
            process.set_exit_status(0)
            process.seal()
        roots.append(root)
        children.append(calc)
        outputs.append(output)
    source = tmp_path / "original.aiida"
    create_archive(roots, filename=source)
    return source, roots, children, outputs, shared


def test_split_preserves_identity_data_and_call_tree_without_other_roots(three_roots):
    source, roots, children, outputs, shared = three_roots
    original = source.read_bytes()
    count = orm.QueryBuilder().append(orm.Node).count()
    assert {item["uuid"] for item in archives.root_processes(source)} == {
        node.uuid for node in roots
    }
    for index, root in enumerate(roots):
        with archives.single_root_archive(source, root.uuid) as derived:
            assert derived.name == f"{root.uuid}.aiida"
            assert archives.root_processes(derived) == (
                {
                    "uuid": root.uuid,
                    "label": root.label,
                    "process_label": "TestWorkChain",
                },
            )
            with archives.archive_backend(derived) as backend:
                nodes = {
                    node.uuid: node
                    for node in orm.QueryBuilder(backend=backend)
                    .append(orm.Node)
                    .all(flat=True)
                }
                assert {
                    root.uuid,
                    children[index].uuid,
                    outputs[index].uuid,
                    shared.uuid,
                } <= set(nodes)
                assert not (
                    {other.uuid for other in roots if other is not root} & set(nodes)
                )
                assert nodes[outputs[index].uuid].get_content() == f"result {index}"
                if index:
                    # Upstream data remains, without its unrelated creating workflow.
                    assert outputs[index - 1].uuid in nodes
        assert not derived.exists()
    assert source.read_bytes() == original
    assert orm.QueryBuilder().append(orm.Node).count() == count


def test_validate_rejects_multi_root_and_wrong_root(three_roots):
    source, roots, *_ = three_roots
    with pytest.raises(ValueError, match="exactly one main process"):
        archives.validate_root(source, roots[0].uuid)
    with (
        archives.single_root_archive(source, roots[0].uuid) as derived,
        pytest.raises(ValueError, match="matching WFMS_UUID"),
    ):
        archives.validate_root(derived, roots[1].uuid)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        ["11111111-1111-1111-1111-111111111111"],
        "",
        "not-uuid",
        "11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222",
    ],
)
def test_uuid_contract_rejects_missing_or_multivalue(value):
    with pytest.raises(ValueError, match="WFMS_UUID"):
        archives.workflow_uuid(value)
