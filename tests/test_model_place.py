"""A model is tracked in place (scenarios E12, owner 11-10): a full train writes it into the folder bitt assigns in its env's task folders
(<tasks>/<task>/artifacts/<cycle>/<line>/<run>/); bitt records its files (path, size, sha256) and where they sit, never a copy. A job
that uses it runs where it is (its folder linked as input/<role>), or is refused with where it is; artifact.copy brings it to another
env (hashed there); artifact.remove is a person's, deletes the files in one env, and keeps the record. On every backend."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from bitt import Refused, blobs
from bitt.tools import envs
from bitt.tools.artifact import places
from bitt.tools.run import land
from test_run import USR, recipe, world
from test_train import setup


def trained(k, c, x, ds, tr, ev, env="local"):
    for _ in range(2):                                     # the smoke run, then the full train
        made = land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf", env=env)["job"])
    return made


def two_envs(tmp_path, monkeypatch):
    """`local`, and `box`: the ssh adapter in local-shell mode (host ""), with its own job and task folders (a second machine)."""
    p = tmp_path / "envs.yaml"
    p.write_text(json.dumps({"local": {"type": "local", "max_sensitivity": "company"},
                             "box": {"type": "ssh", "host": "", "workdir": str(tmp_path / "remote"), "tasks": str(tmp_path / "remote-tasks"),
                                     "python": sys.executable, "max_sensitivity": "company"}}))
    monkeypatch.setenv("BITT_ENVS", str(p))


def test_a_train_writes_its_model_where_bitt_says_and_bitt_keeps_only_its_hashes(opener, tmp_path):
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev)
    p = k.node(made["model"])["payload"]
    folder = tmp_path / "tasks" / "t" / "artifacts" / "c1" / "clf" / made["run"][:12]
    assert p["at"] == {"env": "local", "path": str(folder), "rel": f"t/artifacts/c1/clf/{made['run'][:12]}"}, \
        "the model sits in the task's folder: artifacts/<cycle>/<line>/<run>"
    on_disk = (folder / "weights.json").read_bytes()
    assert p["files"] == [{"path": "weights.json", "size": len(on_disk), "sha256": hashlib.sha256(on_disk).hexdigest()}] \
        and p["size"] == len(on_disk), "its files are recorded by name, size and sha256"
    assert "content_blob" not in p and not any(f.read_bytes() == on_disk for f in Path(blobs.root()).rglob("*") if f.is_file()), \
        "and never copied into bitt's store"
    assert len(list((tmp_path / "jobs").rglob("weights.json"))) == 1, "nor in the job's folder (only the smoke run's scratch is there)"


def test_a_model_on_another_env_is_used_there_refused_here_until_copied(opener, tmp_path, monkeypatch):
    two_envs(tmp_path, monkeypatch)
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev, env="box")
    at = k.node(made["model"])["payload"]["at"]
    assert at["env"] == "box" and Path(at["path"]).is_relative_to(tmp_path / "remote-tasks"), "written on the box, in its task folders"
    assert len(list((tmp_path / "jobs").rglob("weights.json"))) == 1, "the copy back brought the hashes, not the model (one: the smoke's)"
    pred = recipe(c, x, "clf_endpoint", cols={"text": "title"})
    on_box = recipe(c, x, "clf_endpoint", cols={"text": "body"})          # other work: the same work would be reused, not rerun
    run_box = c("run.go", in_=x, recipe=on_box, on=[ds], full="yes", env="box")["run"]
    assert k.node(run_box)["payload"]["env"] == "box" and (tmp_path / "remote").rglob("input/file").__next__().is_symlink(), \
        "a job on the box uses it in place: input/file is a link to its folder there"
    with pytest.raises(Refused, match="is not on env 'local'; it is on \\['box'\\]"):
        c("run.go", in_=x, recipe=pred, on=[ds], full="yes")
    cp = c("artifact.copy", in_=x, target=made["model"], to="local")["copy"]
    assert k.node(cp)["payload"]["path"] == str(tmp_path / "tasks" / at["rel"]) and \
        [pl["env"] for pl in places(k, made["model"])] == ["box", "local"], "a copy hashed on arrival adds a place"
    with pytest.raises(Refused, match="artifact.not_on_env"):
        c("artifact.copy", in_=x, target=made["model"], to="local")
    assert c("run.go", in_=x, recipe=pred, on=[ds], full="yes")["run"], "and the job runs here now"


def test_removing_a_model_is_a_persons_keeps_its_record_and_says_what_was_made_from_it(opener, tmp_path):
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev)
    folder = Path(k.node(made["model"])["payload"]["at"]["path"])
    with pytest.raises(Refused, match="artifact.by_person"):
        c("artifact.remove", in_=x, target=made["model"], env="local")
    assert folder.is_dir(), "an agent's removal deletes nothing"
    out = c("artifact.remove", USR, in_=x, target=made["model"], env="local")
    assert any("made from it" in w for w in out.get("warnings", [])), "the endpoint serving it is made from it: said, not refused"
    assert not folder.exists() and k.node(made["model"])["kind"] == "artifact" and places(k, made["model"]) == [], \
        "the files are gone, the record stays"
    with pytest.raises(Refused, match="artifact.on_env"):
        c("artifact.remove", USR, in_=x, target=made["model"], env="local")
    with pytest.raises(Refused, match="was removed"):
        c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[ds], full="yes")


def test_a_model_folder_deleted_outside_bitt_is_refused_with_what_to_do(opener, tmp_path):
    import shutil
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev)
    shutil.rmtree(k.node(made["model"])["payload"]["at"]["path"])
    with pytest.raises(Refused, match="that folder is gone"):
        c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[ds], full="yes")


def test_a_file_is_never_added_as_a_model_in_place(opener):
    k, c, t, x, raw = world(opener())
    rub = c("artifact.add", in_=x, content=b"be kind", artifact_kind="rubric", name="tone", does="a rubric")["artifact"]
    with pytest.raises(Refused, match="artifact.is_model"):
        c("artifact.remove", USR, in_=x, target=rub, env="local")


def test_the_host_shell_expands_a_home_path():
    box = envs.SSHEnv({"name": "box", "type": "ssh", "host": "", "workdir": "/w"})
    assert box.q("~/bitt-tasks/t") == '"$HOME"/bitt-tasks/t' and box.q("/a b") == "'/a b'"
    assert box.tasks_root() == "~/bitt-tasks", "a host's task folders default to ~/bitt-tasks there"


def test_the_cli_lists_models_shows_where_they_are_and_removes_only_with_yes(pg_dsn, tmp_path, monkeypatch, capsys):
    from bitt import cli
    from bitt.record.postgres import PostgresRecord
    k, c, t, x, raw = world(PostgresRecord(pg_dsn))
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev)
    folder = Path(k.node(made["model"])["payload"]["at"]["path"])
    monkeypatch.setenv("BITT_DSN", pg_dsn)

    def run(*argv):
        code = cli.main(list(argv))
        o = capsys.readouterr()
        return code, o.out + o.err
    code, out = run("--as", "usr", "artifact", "models")
    assert code == 0 and "t/clf" in out and "t#1" in out and f"local:{folder}" in out and "1 model(s)" in out, out
    code, out = run("--as", "usr", "show", made["model"])
    assert code == 0 and "weights.json" in out and f"on local: {folder}" in out, out
    code, out = run("--as", "usr", "artifact", "rm", made["model"])
    assert code == 0 and "would delete 1 model(s)" in out and "made from it: " in out and folder.is_dir(), "without --yes: shown, kept"
    code, out = run("--as", "agent:t", "artifact", "rm", made["model"], "--yes")
    assert code != 0 and "artifact.by_person" in out and folder.is_dir(), "an agent cannot delete a model"
    code, out = run("--as", "usr", "artifact", "rm", "--cycle", "t#1", "--yes")
    assert code == 0 and "removed t/clf" in out and not folder.exists(), out
    code, out = run("--as", "usr", "show", made["model"])
    assert "removed on local by usr" in out, out


def test_jobs_clean_deletes_finished_job_folders_here_and_on_the_env_never_a_model(pg_dsn, tmp_path, monkeypatch, capsys):
    from bitt import cli
    from bitt.record.postgres import PostgresRecord
    two_envs(tmp_path, monkeypatch)
    k, c, t, x, raw = world(PostgresRecord(pg_dsn))
    ds, tr, ev = setup(k, c, x, raw)
    made = trained(k, c, x, ds, tr, ev, env="box")
    folder = Path(k.node(made["model"])["payload"]["at"]["path"])
    monkeypatch.setenv("BITT_DSN", pg_dsn)
    remote = [p for p in (tmp_path / "remote").iterdir()]
    assert len(remote) == 2 and folder.is_dir()

    def run(*argv):
        code = cli.main(list(argv))
        o = capsys.readouterr()
        return code, o.out + o.err
    code, out = run("--as", "agent:t", "jobs", "clean")
    assert code == 0 and "2 on box" in out and all(p.exists() for p in remote), "without --yes: shown, kept"
    code, out = run("--as", "agent:t", "jobs", "clean", "--yes")
    assert code == 0 and "deleted" in out, out
    assert not any(p.exists() for p in remote) and not any((tmp_path / "jobs").iterdir()), "gone on the box and here"
    assert folder.is_dir() and places(k, made["model"]), "the model is not a job folder: kept"
    code, out = run("--as", "agent:t", "jobs", "clean")
    assert "no finished job folders" in out, out
    tr2 = recipe(c, x, "nb_train", cols={"text": "body", "label": "qid"})
    live = c("run.go", in_=x, recipe=tr2, on=[ds], evals=[ev], env="box")["job"]       # not landed: running in the record
    code, out = run("--as", "agent:t", "jobs", "clean", "--yes")
    assert "1 running, kept" in out and (tmp_path / "remote" / live).exists(), "a running job's folder is never deleted"
