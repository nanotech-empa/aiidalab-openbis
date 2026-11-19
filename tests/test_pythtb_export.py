"""Stored native provenance only: no solver, transport or openBIS publication."""

import hashlib
import io
import json
from uuid import uuid4

import numpy as np
import pytest
from aiida import orm
from aiida.common.links import LinkType
from aiida.tools.archive import create_archive
from ase import Atoms

from aiida_openbis.export import available_results, plan_export
from src import aiida_archives, aiida_utils, pythtb_export, simulation_schema


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def make_job(*, periodic=False, hubbard=False, parent=None, source=None, converged=True, operation="orbital"):
    """Synthetic stored outputs for adapter tests; does not execute scientific code."""
    if source is None:
        source = orm.StructureData(ase=Atoms('C2', positions=[[0, 0, 0], [1.42, 0, 0]],
                                            cell=[3, 10, 10], pbc=[periodic, False, False])).store()
    comp = orm.Computer(label='export-test-'+str(uuid4()), hostname='localhost',
                        transport_type='core.local', scheduler_type='core.direct', workdir='/tmp').store()
    code = orm.InstalledCode(label='pythtb', computer=comp, filepath_executable='/stored/native/worker',
                             default_calc_job_plugin='empa_tb.calculate').store()
    if parent is None:
        atoms = source.get_ase()
        request = {'protocol':pythtb_export.PROTOCOL,'engine_sha256':'e'*64,
                   'atoms':{'numbers':atoms.numbers.tolist(),'positions':atoms.positions.tolist(),
                            'cell':atoms.cell.array.tolist(),'pbc':atoms.pbc.tolist()},
                   'source_structure_uuid':source.uuid,'U':2.0 if hubbard else None,
                   'hoppings':[-2.7],'scf_tol':1e-8,'scf_max_iter':500,'n_kpts':2,'k_path':'G X'}
        mf = {'converged':converged,'n_iter':5,'density_change':1e-9 if converged else .1,'tolerance':1e-8} if hubbard else None
        summary = {'protocol':pythtb_export.PROTOCOL,'engine_sha256':'e'*64,
                   'request_sha256':digest(request),'status':'completed' if converged else 'not_converged',
                   'spinful':hubbard,'mf':mf,'k_labels':['Γ','X'] if periodic else None}
        arrays = {'band_energies':np.array([[-2.7,2.7],[-2.,2.]]) if periodic else np.array([-2.7,2.7])}
        if periodic:arrays.update(k_dist=np.array([0.,1.]),k_node=np.array([0.,1.]),k_vec=np.array([[0.],[.5]]))
        if hubbard:
            arrays.update(energies_up=arrays['band_energies'].copy(),energies_down=arrays['band_energies'].copy(),
                          mf_n_up=np.array([.5,.5]),mf_n_dn=np.array([.5,.5]))
        inputs={'request':orm.Dict(dict=request).store(),'source_structure':source,'code':code}
    else:
        base=parent.inputs.request.get_dict()
        request={'protocol':pythtb_export.PROTOCOL,'engine_sha256':'e'*64,'operation':operation,
                 'reference_uuid':parent.uuid,'base_request':base,'base_request_sha256':digest(base),
                 'band_index':0,'k_index':0}
        summary=dict(parent.outputs.summary.get_dict(),request_sha256=digest(request),operation='orbital',
                     reference_uuid=parent.uuid,orbital_selection={'band_index':0,'k_index':0},reused_mean_field=True)
        with parent.outputs.retrieved.base.repository.open('result.npz','rb') as handle:
            with np.load(io.BytesIO(handle.read()),allow_pickle=False) as data:
                arrays={k:data[k].copy() for k in data.files if k!='summary'}
        arrays.update(orbital_vector=np.array([1.,1.])/np.sqrt(2),orbital_eigenvalues=np.array([-2.7,2.7]))
        if operation == "wannier":
            settings = {"energy_label": "E - neutral reference (eV)", "cutoff_ev": .01}
            request.update(wannier_settings=settings, postprocess_engine_sha256="w"*64)
            summary.update(operation=operation, request_sha256=digest(request),
                           postprocess_engine_sha256="w"*64,
                           status="completed" if converged else "not_converged",
                           wannier={"settings": settings, "converged": converged,
                                    "channels": {"up": {"localization_converged": converged,
                                                        "metrics": {"roundtrip_precision": 1/3},
                                                        "disentanglement_converged": None}}})
            arrays.update(wannier_up_check_k=np.array([[-.5],[.5]]),
                          wannier_up_simplified_bands=np.array([[-1.,1.],[-2.,2.]]))
        inputs={'request':orm.Dict(dict=request).store(),'source_structure':source,'code':code,
                'reference_request':parent.inputs.request,'reference_result':parent.outputs.retrieved}
    root=orm.CalcJobNode(process_type=pythtb_export.PROCESS_TYPE)
    root.set_process_label('PythtbCalculation')
    for name,value in inputs.items():root.base.links.add_incoming(value,LinkType.INPUT_CALC,name)
    root.store()
    out=orm.Dict(dict=summary);out.base.links.add_incoming(root,LinkType.CREATE,'summary');out.store()
    data=io.BytesIO();np.savez_compressed(data,summary=np.asarray(json.dumps(summary)),**arrays)
    folder=orm.FolderData();folder.put_object_from_filelike(io.BytesIO(data.getvalue()),'result.npz')
    folder.base.links.add_incoming(root,LinkType.CREATE,'retrieved');folder.store()
    root.set_process_state('finished');root.set_exit_status(0 if converged else 302);root.seal()
    return root


def assert_schema(definitions):
    for row in definitions.values():
        assignments=simulation_schema.OBJECT_TYPES[row['object_type']]['assignments']
        allowed={a['code'].lower() for a in assignments}
        mandatory={a['code'].lower() for a in assignments if a['mandatory']}
        assert set(row['properties']) <= allowed
        assert mandatory <= set(row['properties'])


@pytest.mark.parametrize('periodic,hubbard,roles',[(False,False,{'levels'}),(True,False,{'bands'}),
                                                (True,True,{'bands','charge'})])
def test_native_definitions_keep_real_process_identity_and_units(aiida_profile_clean,periodic,hubbard,roles):
    node=make_job(periodic=periodic,hubbard=hubbard)
    defs=pythtb_export.definitions(node);assert set(defs)==roles;assert_schema(defs)
    for row in defs.values():
        props=row['properties'];assert props['aiida_source_uuid']==node.uuid
        assert props['converged'] is True
        assert 'spin_multiplicity' not in props and 'total_energy_hartree' not in props
        meta=json.loads(props['comments']);assert meta['code_uuid']==node.inputs.code.uuid
        assert meta['computer_uuid']==node.inputs.code.computer.uuid
        assert meta['worker_engine_sha256']=='e'*64
        assert meta['provenance'].startswith('Native AiiDA')
        assert 'software' not in meta # No notebook versions substituted for worker observations.
    assert pythtb_export.structures(node,next(iter(roles)))==([node.inputs.source_structure.uuid],[])
    plan=plan_export(node.uuid);assert plan['source_uuid']==node.uuid and plan['results']==defs
    assert {'filename':'result.npz','uuid':node.outputs.retrieved.uuid} in plan['stored_files']


def test_exact_model_reference_scope_and_no_same_structure_contamination(aiida_profile_clean):
    parent=make_job();orbital=make_job(parent=parent,source=parent.inputs.source_structure)
    other=make_job(source=parent.inputs.source_structure)
    related=available_results(parent.uuid)
    assert {r['uuid'] for r in related}=={parent.uuid,orbital.uuid}
    assert {r['uuid'] for r in available_results(orbital.uuid)}=={parent.uuid,orbital.uuid}
    assert other.uuid not in aiida_utils.get_export_main_workchains(parent.uuid)
    assert {n.uuid for n in aiida_utils._exportable_workchains(parent)}=={parent.uuid,orbital.uuid}
    assert set(pythtb_export.definitions(orbital))=={'orbitals'}
    assert_schema(pythtb_export.definitions(orbital))
    assert 'volumetric' in pythtb_export.definitions(orbital)['orbitals']['properties']['simulation_description']


def test_partial_mfh_is_explicitly_unconverged(aiida_profile_clean):
    node=make_job(periodic=True,hubbard=True,converged=False)
    assert aiida_utils.export_ready(node)
    assert all(not r['properties']['converged'] for r in pythtb_export.definitions(node).values())


def test_previews_and_single_root_archives_use_only_stored_data(aiida_profile_clean,tmp_path,monkeypatch):
    from aiida.transports import Transport
    def forbidden(*args,**kwargs):pytest.fail('Export must not open a transport or execute a solver')
    monkeypatch.setattr(Transport,'open',forbidden)
    import aiida.engine
    monkeypatch.setattr(aiida.engine,'submit',forbidden)
    parent=make_job(periodic=True,hubbard=True);child=make_job(parent=parent,source=parent.inputs.source_structure)
    for node in [parent,child]:
        for role in pythtb_export.definitions(node):
            path=tmp_path/(node.uuid+'-'+role+'.png');pythtb_export.render_preview(node.uuid,role,path)
            assert path.stat().st_size>100
        archive=tmp_path/(node.uuid+'.aiida')
        create_archive([node],filename=archive,include_authinfos=False,call_calc_backward=False,
                       call_work_backward=False,create_backward=False)
        assert aiida_archives.validate_root(archive,node.uuid)==node.uuid
        with aiida_archives.archive_backend(archive) as backend:
            stored=orm.QueryBuilder(backend=backend).append(orm.CalcJobNode).all(flat=True)
            assert [n.uuid for n in stored]==[node.uuid]


def test_request_manifest_mismatch_refused(aiida_profile_clean,monkeypatch):
    node=make_job()
    original=orm.Dict.get_dict
    def bad(self):
        result=original(self)
        if self.uuid==node.outputs.summary.uuid:result['request_sha256']='wrong'
        return result
    monkeypatch.setattr(orm.Dict,'get_dict',bad)
    with pytest.raises(ValueError,match='does not match'):pythtb_export.definitions(node)


def test_orbital_single_root_keeps_frozen_reference_without_missing_parent_fetch(aiida_profile_clean,tmp_path):
    parent=make_job();child=make_job(parent=parent,source=parent.inputs.source_structure)
    archive=tmp_path/'only-orbital.aiida'
    create_archive([child],filename=archive,include_authinfos=False,call_calc_backward=False,
                   call_work_backward=False,create_backward=False)
    with aiida_archives.archive_backend(archive) as backend:
        stored=orm.QueryBuilder(backend=backend).append(orm.CalcJobNode).one()[0]
        defs=pythtb_export.definitions(stored)
        meta=json.loads(defs['orbitals']['properties']['comments'])
        assert meta['model_source_uuid']==parent.uuid and meta['model_process_present'] is False
        assert_schema(defs)


@pytest.mark.parametrize("converged", [True, False])
def test_wannier_is_exact_linked_native_result_not_repeated_charge(aiida_profile_clean, tmp_path, converged):
    parent = make_job(periodic=True, hubbard=True)
    child = make_job(parent=parent, source=parent.inputs.source_structure,
                     operation="wannier", converged=converged)
    defs = pythtb_export.definitions(child)
    assert set(defs) == {"wannier"}
    assert_schema(defs)
    props = defs["wannier"]["properties"]
    assert props["converged"] is converged
    metadata = json.loads(props["comments"])
    assert metadata["model_source_uuid"] == parent.uuid
    assert metadata["postprocess_engine_sha256"] == "w"*64
    assert metadata["energy_reference"] == "E - neutral reference (eV)"
    assert metadata["wannier"]["channels"]["up"]["metrics"]["roundtrip_precision"] == 1/3
    assert {r["uuid"] for r in available_results(parent.uuid)} == {parent.uuid, child.uuid}
    preview = tmp_path / "wannier.png"
    pythtb_export.render_preview(child.uuid, "wannier", preview)
    assert preview.stat().st_size > 100
