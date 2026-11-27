"""Detection on another computer over SSH ("Run detection on: another computer").

Only the heavy step moves: the app, the review, the report and every file stay on this computer.

  1. upload   the folder's TIFFs are streamed as a tar archive through `ssh <host> tar -x` (Python's tarfile on this
              side, so it works the same on macOS and Windows: both ship an OpenSSH client, Windows has no rsync and
              scp trips over spaces and commas in file names)
  2. detect   `<remote command> run <job>/in/<folder> --out <job>/out --no-library --cancel-file <job>/cancel`;
              its output lines drive the same progress bar as a local run
  3. download `ssh <host> tar -c` of the results, unpacked into the local <folder>_kidneycyst
  4. finish   paths and provenance rewritten for this computer, tables, report, saved runs and the "detected"
              snapshot made locally; the remote job folder is deleted (only that folder)

Requirements on the other computer: SSH login with a key (no password prompt: the app cannot type one) and KidneyCyst
installed. Settings live in <install>/remote_gpu.json (or ~/.kidneycyst/remote_gpu.json).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if WIN else 0           # CREATE_NO_WINDOW: no console flashes from pythonw on Windows
HOST_RE = re.compile(r"^[A-Za-z0-9_.@:\[\]%-]+$")
JOBS_DIR = "~/.kidneycyst_jobs"
CANDIDATES = [                                   # tried in this order when no command is set
    "kidneycyst",
    "~/KidneyCyst-remote/files/env/bin/python -m kidneycyst.cli",
    "~/KidneyCyst/files/env/bin/python -m kidneycyst.cli",
    "~/KidneyCyst/KidneyCyst/files/env/bin/python -m kidneycyst.cli",
    "~/Documents/KidneyCyst/files/env/bin/python -m kidneycyst.cli",
    "~/Documents/KidneyCyst/KidneyCyst/files/env/bin/python -m kidneycyst.cli",
    "~/KidneyCyst/env/bin/python -m kidneycyst.cli",
    "python3 -m kidneycyst.cli",
]


# searched when none of CANDIDATES works: kidneycyst in any Python under the home folder (40 s at most), conda envs
SEARCH = ("for py in $( { timeout 40 find ~ -maxdepth 8 -path '*site-packages/kidneycyst/cli.py' 2>/dev/null | "
          "sed 's#/lib/python[^/]*/site-packages/kidneycyst/cli.py$#/bin/python#'; "
          "conda env list 2>/dev/null | awk '!/^#/ && NF {print $NF \"/bin/python\"}'; } | sort -u | head -20 ); do "
          "[ -x \"$py\" ] || continue; c=\"$py -m kidneycyst.cli\"; "
          "out=$(eval \"$c info $S\" 2>/dev/null | grep '^KIDNEYCYST_INFO ') && [ -n \"$out\" ] && "
          "{ echo \"KIDNEYCYST_CMD $c\"; echo \"$out\"; exit 0; }; done; ")
REMOTE_HOME = "~/KidneyCyst-remote"              # made by "Install KidneyCyst there"; its own folder, nothing else in it
UV_VERSION = "0.9.5"


class RemoteError(Exception):
    """A problem described in plain words for the app."""


# ---------------------------------------------------------------- settings
def _settings_path() -> Path:
    from .qupath_io import install_home
    h = install_home()
    d = h if h is not None else Path.home() / ".kidneycyst"
    d.mkdir(parents=True, exist_ok=True)
    return d / "remote_gpu.json"


def _backup_path() -> Path:
    """Copy of the settings in the user's home folder: a fresh install (which replaces the install folder) keeps them."""
    return Path.home() / ".kidneycyst" / "remote_gpu.json"


def load_settings() -> dict:
    s = {}
    for f in (_settings_path(), _backup_path()):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            break
        except Exception:
            continue
    return dict(enabled=bool(s.get("enabled")), host=s.get("host", ""), command=s.get("command", ""),
                info=s.get("info") or {}, slurm=bool(s.get("slurm")), slurm_options=s.get("slurm_options", ""),
                partitions=s.get("partitions") or [])


def save_settings(**kw) -> dict:
    s = load_settings()
    s.update({k: v for k, v in kw.items() if k in ("enabled", "host", "command", "info", "slurm", "slurm_options", "partitions")})
    if s.get("slurm_options"):
        slurm_args(s["slurm_options"])                  # refuse anything that is not a plain option
    s["host"] = str(s["host"]).strip()
    s["command"] = str(s["command"]).strip()
    if s["enabled"] and not s["host"]:
        s["enabled"] = False
    for p in dict.fromkeys((_settings_path(), _backup_path())):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            if p == _settings_path():
                raise
    return s


def known_command(host: str) -> str:
    """The command that last worked for this computer (kept in the home folder, so a reinstall does not lose it)."""
    try:
        return json.loads(_backup_path().with_name("remote_hosts.json").read_text(encoding="utf-8")).get(host, "")
    except Exception:
        return ""


def remember_command(host: str, command: str):
    f = _backup_path().with_name("remote_hosts.json")
    try:
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        d[host] = command
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- ssh
def ssh_exe() -> str | None:
    f = shutil.which("ssh")
    if f:
        return f
    if WIN:
        p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
        if p.exists():
            return str(p)
    return None


def _check_host(host: str) -> str:
    host = (host or "").strip()
    if not host or host.startswith("-") or not HOST_RE.match(host):
        raise RemoteError("Enter the other computer's name or address, for example gpu-box or user@10.1.2.3.")
    return host


def _ssh_args(host: str, remote_cmd: str) -> list[str]:
    exe = ssh_exe()
    if exe is None:
        raise RemoteError("No SSH program found on this computer. macOS includes one; on Windows 10/11 add "
                          "'OpenSSH Client' under Settings > Apps > Optional features.")
    host = _check_host(host)
    port = []
    m = re.match(r"^(.*[^:\]]):(\d{1,5})$", host)      # name@host:2222 (an IPv6 address needs [brackets])
    if m:
        host, port = m.group(1), ["-p", m.group(2)]
    return [exe, "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=accept-new", *port, "--", host.strip("[]"),
            remote_cmd]


def _sh(script: str) -> str:
    """Run a POSIX script on the remote through a login shell (non-interactive ssh has a minimal PATH)."""
    return "sh -lc " + shlex.quote(script)


def _popen(host, remote_cmd, **kw):
    return subprocess.Popen(_ssh_args(host, remote_cmd), creationflags=NO_WINDOW, **kw)


def _run(host, remote_cmd, timeout=60, stdin=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(_ssh_args(host, remote_cmd), capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL if stdin is None else stdin, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RemoteError(f"{host} did not answer within {timeout} s.")


def explain(stderr: str, host: str) -> str:
    e = stderr or ""
    if "Permission denied" in e:
        return (f"{host} refused the login without a password. The app can only use key login. "
                f"Click 'Set up key login' (you type your password once).")
    if "Could not resolve hostname" in e or "Name or service not known" in e or "nodename nor servname" in e:
        return f"The name {host} is unknown to this computer. Check the spelling, or use its address (for example 10.1.2.3)."
    if "timed out" in e or "No route to host" in e or "Network is unreachable" in e:
        return f"{host} cannot be reached. Check the VPN or network connection, and that the computer is on."
    if "Connection refused" in e:
        return f"{host} does not accept SSH connections."
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in e or "Host key verification failed" in e:
        return (f"{host} presents a different identity than last time (it may have been reinstalled). "
                f"Ask IT, or remove the old entry from the known_hosts file in your .ssh folder.")
    last = [l for l in e.strip().splitlines() if l.strip()]
    return f"Connection to {host} failed: {last[-1] if last else 'unknown error'}"


# ---------------------------------------------------------------- test connection
def probe(host: str, command: str = "") -> dict:
    """Connect, find KidneyCyst, ask it for version / model / GPU. Never raises; returns steps for the dialog."""
    res = dict(ok=False, host=host, steps=[], command="", info={}, slurm=False, partitions=[], slurm_default="")
    try:
        host = _check_host(host)
        t0 = time.time()
        r = _run(host, "echo KIDNEYCYST_OK", timeout=30)
        if "KIDNEYCYST_OK" not in r.stdout:
            res["steps"].append(dict(ok=False, text=explain(r.stderr, host), needs_key="Permission denied" in r.stderr))
            return res
        res["steps"].append(dict(ok=True, text=f"Connected to {host} ({time.time() - t0:.1f} s)."))
        known = known_command(host)
        cands = [command] if command else ([known] if known else []) + [c for c in CANDIDATES if c != known]
        # a cluster login node (sbatch present) must not compute: skip its GPU check, list the GPU partitions instead
        script = "S=; if command -v sbatch >/dev/null 2>&1; then S=--no-device; echo KIDNEYCYST_SLURM; " \
                 "sinfo -h -o '%P %G' 2>/dev/null | sed 's/^/KIDNEYCYST_PART /'; fi; " \
                 "for c in " + " ".join(shlex.quote(c) for c in cands) + "; do " \
                 "out=$(eval \"$c info $S\" 2>/dev/null | grep '^KIDNEYCYST_INFO ') && [ -n \"$out\" ] && " \
                 "{ echo \"KIDNEYCYST_CMD $c\"; echo \"$out\"; exit 0; }; done; " + ("" if command else SEARCH) + "exit 3"
        r = _run(host, _sh(script), timeout=180)
        m_cmd = re.search(r"^KIDNEYCYST_CMD (.+)$", r.stdout, re.M)
        m_inf = re.search(r"^KIDNEYCYST_INFO (.+)$", r.stdout, re.M)
        if not (m_cmd and m_inf):
            res["can_install"] = True
            res["steps"].append(dict(ok=False, text=(
                f"The command '{command}' did not start KidneyCyst on {host}. Check it under Advanced, or clear it to "
                f"search automatically." if command else
                f"KidneyCyst is not installed on {host} (the usual places, your home folder and conda environments were "
                f"searched).")))
            res["steps"].append(dict(ok=True, warn=True, text=(
                "Click 'Install KidneyCyst there' and the app sets it up for you: it copies the program and model from this "
                "computer and downloads Python and PyTorch there (about 10 minutes, 8 GB in your home folder there). "
                "If KidneyCyst is already installed there in another place, open Advanced and enter the command that "
                "starts it instead.")))
            return res
        info = json.loads(m_inf.group(1))
        res["command"], res["info"] = m_cmd.group(1).strip(), info
        remember_command(host, res["command"])
        res["steps"].append(dict(ok=True, text=f"KidneyCyst {info.get('tool_version', '?')} found."))
        from . import __version__ as here
        there = str(info.get("tool_version", ""))
        if there and there != here:
            ours = REMOTE_HOME.lstrip("~/") in res["command"]
            res["can_install"] = ours                   # our own copy there: "Install KidneyCyst there" updates it
            res["steps"].append(dict(ok=True, warn=True, text=(
                f"{host} has KidneyCyst {there}; this computer has {here}. "
                + ("Click Install KidneyCyst there to bring it to the same version." if ours else
                   "Update it there so both computers measure the same way."))))
        model = model_label(str(info.get("model_source", info.get("checkpoint", ""))))
        res["steps"].append(dict(ok=True, text=f"Model: {model}."))
        local = _local_model()
        if local and model != "?" and local != model:
            res["steps"].append(dict(ok=True, warn=True, text=f"This computer has a different model ({local}). "
                                     f"Results will come from the other computer's model; the report records which."))
        if "KIDNEYCYST_SLURM" in r.stdout:
            parts, typed = [], []
            for m in re.finditer(r"^KIDNEYCYST_PART (\S+) (.*)$", r.stdout, re.M):
                name = m.group(1).rstrip("*")
                if "gpu" in m.group(2) and name not in parts:
                    parts.append(name)
                    if re.search(r"gpu:[A-Za-z]", m.group(2)):
                        typed.append(name)            # GPUs named by model: usually the newer nodes
            res.update(slurm=True, partitions=parts, slurm_default=default_slurm_options(typed + [p for p in parts if p not in typed]))
            res["steps"].append(dict(ok=bool(parts), text=(
                f"Job queue (Slurm) found: detection runs as a job on a GPU node, not on {host} itself. "
                f"Partitions with GPUs: {', '.join(parts)}." if parts else
                f"{host} has a job queue (Slurm) but no partition with GPUs was found.")))
        else:
            dev = info.get("device", "cpu")
            res["steps"].append(dict(ok=True, warn=dev == "cpu",
                                     text=(f"Graphics card: {info.get('device_name', dev)}." if dev != "cpu" else
                                           f"{host} has no usable graphics card: detection there runs on its CPU.")))
        if info.get("error"):
            res["steps"].append(dict(ok=False, text=f"KidneyCyst on {host} reports a problem: {info['error']}"))
            return res
        res["ok"] = True
    except RemoteError as e:
        res["steps"].append(dict(ok=False, text=str(e)))
    except Exception as e:
        res["steps"].append(dict(ok=False, text=f"{type(e).__name__}: {e}"))
    return res


def model_label(src: str) -> str:
    """KC009 / KC007 from the model's source folder; otherwise the folder name."""
    n = Path(src.split("source:", 1)[-1].strip()).name
    for key, name in (("250epochs", "KC009 (250 epochs)"), ("100epochs", "KC007 (100 epochs)")):
        if key in n:
            return name
    return n or "?"


def _local_model() -> str:
    try:
        from . import cli
        ck = Path(cli.default_checkpoint())
        mt = ck / "MODEL.txt"
        return model_label(mt.read_text().splitlines()[0] if mt.exists() else str(ck))
    except Exception:
        return ""


def _port_args(host: str) -> str:
    m = re.match(r"^(.*[^:\]]):(\d{1,5})$", host)
    return f"-p {m.group(2)} {shlex.quote(m.group(1))}" if m else shlex.quote(host)


# ---------------------------------------------------------------- key setup (one password prompt, in a terminal)
def open_key_setup(host: str) -> dict:
    """Open a terminal window that creates a key (if none) and copies it to the other computer."""
    host = _check_host(host)
    if WIN:
        ps = (
            "$k=\"$env:USERPROFILE\\.ssh\\id_ed25519\"; if(!(Test-Path $k)){ ssh-keygen -t ed25519 -N '\"\"' -f $k }; "
            f"Write-Host 'Type your password for {host} once:'; "
            f"Get-Content \"$k.pub\" | ssh {_port_args(host)} \"umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys\"; "
            "Write-Host ''; Write-Host 'Done. Close this window and click Test connection.'")
        subprocess.Popen(["cmd", "/c", "start", "KidneyCyst key setup", "powershell", "-NoExit", "-Command", ps])
        return dict(ok=True)
    sh = ("k=~/.ssh/id_ed25519; [ -f $k ] || ssh-keygen -t ed25519 -N '' -f $k -q; "
          f"echo 'Type your password for {host} once:'; "
          f"cat $k.pub | ssh {_port_args(host)} 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys' && "
          "echo && echo 'Done. Close this window and click Test connection.'")
    if sys.platform == "darwin":
        osa = 'tell application "Terminal" to do script ' + json.dumps(sh) + '\ntell application "Terminal" to activate'
        subprocess.Popen(["osascript", "-e", osa])
        return dict(ok=True)
    for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            subprocess.Popen(term + ["bash", "-c", sh + "; exec bash"])
            return dict(ok=True)
    return dict(ok=False, manual=sh)


# ---------------------------------------------------------------- one detection job
class Cancelled(Exception):
    """Cancelled by the user before any results existed (the message says when)."""


def run_remote(job, folder: Path, out: Path, extra_args: list[str], log, cancel: threading.Event):
    """Upload, detect, download, finish. `job` is the app's Job (phase / i / n / progress fields), `log` a writable
    text stream whose lines drive the progress bar exactly as a local run does."""
    from . import cli
    st = load_settings()
    host, cmd = _check_host(st["host"]), st["command"]
    if not cmd:
        raise RemoteError("The other computer has not been tested yet. Open 'Run detection on' and click Test connection.")
    jid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    jdir = f"{JOBS_DIR}/{jid}"                          # ~ expanded by the remote shell
    rin = f"{jdir}/in/" + shlex.quote(folder.name)      # jdir is plain ASCII (~ must stay unquoted to expand)
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in cli.TIF_EXT
                   and not any(part.endswith("_kidneycyst") for part in p.relative_to(folder).parts))
    if not files:
        raise RemoteError("No TIFF images found in this folder or its subfolders.")
    total = sum(p.stat().st_size for p in files)
    print(f"Detection on {host}. {len(files)} TIFF images ({total / 1e6:.0f} MB) are copied there first.", file=log, flush=True)

    def remote_cleanup():
        try:
            _run(host, _sh(f"rm -rf {jdir}"), timeout=60)     # jdir = ~/.kidneycyst_jobs/<id>: only this job
        except Exception:
            pass

    try:
        # 1. upload
        job.phase, job.xfer, job.xfer_total = "uploading", 0, total
        p = _popen(host, _sh(f"mkdir -p {rin} && tar -xf - -C {rin}"),
                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=_Counting(p.stdin, job), mode="w|", format=tarfile.PAX_FORMAT) as t:
                for f in files:
                    if cancel.is_set():
                        raise Cancelled("Detection cancelled while the images were being copied.")
                    t.add(f, arcname=str(PurePosixPath(*f.relative_to(folder).parts)), recursive=False)
            p.stdin.close()
        except Cancelled:
            p.kill()
            raise
        except OSError:                                   # broken pipe: the remote side failed; its message follows
            pass
        if p.wait() != 0:
            raise RemoteError("Copying the images failed: " + explain(p.stderr.read().decode(errors="replace"), host))

        # 2. detect (the remote output feeds the progress bar)
        job.phase = "loading"
        run_line = (f"{cmd} run {shlex.quote(PurePosixPath('in', folder.name).as_posix())} --out out "
                    f"--no-library --cancel-file cancel " + " ".join(shlex.quote(a) for a in extra_args))
        if st.get("slurm"):
            _run_slurm(job, host, jdir, run_line, st, log, cancel)
        else:
            _run_direct(job, host, jdir, run_line, log, cancel)

        # 3. download the results
        job.phase, job.xfer, job.xfer_total = "downloading", 0, 0
        print(f"Copying the results back from {host}…", file=log, flush=True)
        stage = out.parent / f".{out.name}.incoming-{jid}"
        stage.mkdir(parents=True)
        try:
            p = _popen(host, _sh(f"cd {jdir}/out && tar -cf - ."), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
            with tarfile.open(fileobj=_Counting(p.stdout, job, read=True), mode="r|") as t:
                for m in t:
                    _safe_extract(t, m, stage)
            if p.wait() != 0:
                raise RemoteError("Copying the results back failed: " + explain(p.stderr.read().decode(errors="replace"), host))
            if not (stage / "results.csv").exists():
                raise RemoteError(f"{host} returned no results table.")
            prev = out.parent / f".{out.name}.previous-results-{jid}.csv"
            if (out / "results.csv").exists():
                shutil.copy2(out / "results.csv", prev)   # its human measurements are carried onto the new table
            _merge(stage, out)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        try:
            _finish_locally(out, folder, host, cmd, st.get("info") or {}, prev)
        finally:
            prev.unlink(missing_ok=True)
        print(f"Results copied back from {host}.", file=log, flush=True)
    finally:
        remote_cleanup()


def _run_direct(job, host, jdir, run_line, log, cancel):
    """Run the detection straight on the other computer (a workstation with its own graphics card)."""
    p = _popen(host, _sh(f"cd {jdir} && {run_line}"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
               stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace")
    threading.Thread(target=_cancel_watch, args=(cancel, p, host, jdir), daemon=True).start()
    for line in p.stdout:
        log.write(line)
    if p.wait() != 0 and not cancel.is_set():
        raise RemoteError(f"Detection on {host} stopped with an error. The last lines of its output are in the "
                          f"processing details.")


# ---------------------------------------------------------------- Slurm (cluster login node + job queue)
_OPT_RE = re.compile(r"^--?[A-Za-z][\w-]*(=[\w:.,/@%+=-]*)?$")
_VAL_RE = re.compile(r"^[\w:.,/@%+=-]+$")


def slurm_args(text: str) -> list[str]:
    """Job options typed by the user, as a safe argument list (options and plain values only, no shell syntax)."""
    try:
        toks = shlex.split(text or "")
    except ValueError:
        raise RemoteError("The job options could not be read (check the quotes).")
    for i, t in enumerate(toks):
        if not (_OPT_RE.match(t) or (i and toks[i - 1].startswith("-") and "=" not in toks[i - 1] and _VAL_RE.match(t))):
            raise RemoteError(f"Job option not accepted: {t}. Use options like --partition=gpuq --gres=gpu:1 --time=02:00:00.")
    return toks


def default_slurm_options(parts: list[str]) -> str:
    part = next((p for p in parts if "interactive" not in p.lower()), parts[0] if parts else "")
    return (f"--partition={part} " if part else "") + "--gres=gpu:1 --time=02:00:00 --mem=32G --cpus-per-task=4"


QUEUE_REASON = {"Priority": "other jobs are ahead in the queue", "Resources": "waiting for a free GPU",
                "QOSMaxJobsPerUserLimit": "you already have the maximum number of jobs running",
                "ReqNodeNotAvail": "the requested GPU nodes are unavailable", "None": ""}


def _run_slurm(job, host, jdir, run_line, st, log, cancel):
    """Submit the detection as a batch job and follow it: queue state first, then the job's own output."""
    opts = " ".join(shlex.quote(a) for a in slurm_args(st.get("slurm_options") or default_slurm_options(st.get("partitions") or [])))
    script = f"#!/bin/bash\ncd \"$SLURM_SUBMIT_DIR\"\n{run_line} > log.txt 2>&1\necho $? > exitcode\n"
    r = _run(host, _sh(f"cd {jdir} && printf '%s' {shlex.quote(script)} > job.sh && "
                       f"sbatch --parsable -J kidneycyst -o slurm-%j.out {opts} job.sh"), timeout=90)
    out_lines = [l for l in r.stdout.splitlines() if l.strip()]
    jobid = out_lines[-1].split(";")[0].strip() if out_lines else ""
    if not jobid.isdigit():
        last = [l for l in (r.stderr or "").splitlines() if l.strip()]
        raise RemoteError(f"The job queue on {host} refused the job: {last[-1] if last else 'no reason given'}. "
                          f"Check the job options under 'Detection runs on … Change…'.")
    job.slurm_id, job.phase, job.queue_reason = jobid, "queued", ""
    print(f"Submitted as job {jobid} to the job queue on {host}.", file=log, flush=True)
    off, buf, cancel_sent, finished = 0, "", False, False
    try:
        while True:
            r = _run(host, _sh(f"squeue -h -j {jobid} -o '%T|%r' 2>/dev/null; echo KCSEP; "
                               f"tail -c +{off + 1} {jdir}/log.txt 2>/dev/null"), timeout=60)
            head, _, new = r.stdout.partition("KCSEP\n")
            state, _, reason = head.strip().partition("|")
            if new:
                off += len(new.encode("utf-8"))
                buf += new
                *lines, buf = buf.split("\n")
                for l in lines:
                    log.write(l + "\n")
            if state == "PENDING":
                job.phase, job.queue_reason = "queued", QUEUE_REASON.get(reason, reason)
            elif state in ("RUNNING", "COMPLETING", "CONFIGURING") and job.phase == "queued":
                job.phase, job.queue_reason = "loading", ""
                print(f"Job {jobid} started on a GPU node.", file=log, flush=True)
            if cancel.is_set() and not cancel_sent:
                cancel_sent = True
                if state == "PENDING":                    # never started: withdraw it
                    _run(host, _sh(f"scancel {jobid}"), timeout=30)
                    finished = True
                    raise Cancelled("Detection cancelled before the job started.")
                _run(host, _sh(f"touch {jdir}/cancel"), timeout=30)   # stops after the current image, keeps results
            if not state:
                break
            cancel.wait(3)
        finished = True
        if buf:
            log.write(buf + "\n")
        r = _run(host, _sh(f"cat {jdir}/exitcode 2>/dev/null || echo NONE; echo KCSEP; "
                           f"tail -n 5 {jdir}/slurm-{jobid}.out 2>/dev/null"), timeout=60)
        code, _, tail = r.stdout.partition("KCSEP\n")
        code = code.strip()
        if code == "NONE":
            raise RemoteError(f"Job {jobid} on {host} ended before detection finished (it may have run out of time or "
                              f"memory, or been cancelled). Last lines: "
                              f"{' | '.join(l for l in tail.splitlines() if l.strip())[-300:]}")
        if code != "0" and not cancel.is_set():
            r = _run(host, _sh(f"tail -n 40 {jdir}/log.txt 2>/dev/null"), timeout=60)
            if "no kernel image is available" in r.stdout:
                part = next((a.split("=", 1)[1] for a in slurm_args(st.get("slurm_options") or "") if a.startswith("--partition=")), "")
                raise RemoteError(f"The graphics cards in partition {part or '(default)'} are too old for the PyTorch installed on "
                                  f"{host}. Choose another partition in the job options (Detection runs on … Change…).")
            raise RemoteError(f"Detection in job {jobid} on {host} stopped with an error. The last lines of its output "
                              f"are in the processing details.")
    finally:
        if not finished:                                  # connection lost or app stopped: do not leave a job behind
            try:
                _run(host, _sh(f"scancel {jobid}"), timeout=30)
            except Exception:
                pass


def _cancel_watch(cancel: threading.Event, p, host, jdir):
    while p.poll() is None:
        if cancel.wait(1.0):
            try:                                          # the remote run stops after the current image, keeps results
                _run(host, _sh(f"touch {jdir}/cancel"), timeout=30)
            except Exception:
                pass
            return


class _Counting:
    """File wrapper that counts bytes for the progress bar."""

    def __init__(self, f, job, read=False):
        self.f, self.job, self.read_mode = f, job, read

    def write(self, b):
        n = self.f.write(b)
        self.job.xfer += len(b)
        return n

    def read(self, n=-1):
        b = self.f.read(n)
        self.job.xfer += len(b)
        return b

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def close(self):
        pass


def _safe_extract(t: tarfile.TarFile, m: tarfile.TarInfo, dest: Path):
    name = PurePosixPath(m.name)
    if name.is_absolute() or ".." in name.parts or not (m.isfile() or m.isdir()):
        return                                            # never write outside the staging folder, no links/devices
    target = dest.joinpath(*[p for p in name.parts if p not in (".", "")])
    if m.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    src = t.extractfile(m)
    with open(target, "wb") as fh:
        shutil.copyfileobj(src, fh)


def _merge(stage: Path, out: Path):
    """Move the downloaded results into the local results folder. run.json (local identity) and snapshots stay local."""
    out.mkdir(parents=True, exist_ok=True)
    for item in stage.iterdir():
        if item.name in ("run.json", "snapshots"):
            continue
        dst = out / item.name
        if item.is_dir():
            dst.mkdir(exist_ok=True)
            for f in item.rglob("*"):
                if f.is_file():
                    d = dst / f.relative_to(item)
                    d.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(f, d)
        else:
            os.replace(item, dst)


def _finish_locally(out: Path, folder: Path, host: str, cmd: str, info: dict, prev: Path | None = None):
    import pandas as pd
    from . import report as RP
    from . import library as LIB
    sp = out / "run_settings.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["remote"] = dict(host=host, command=cmd, remote_host_name=s.get("host", ""), remote_input_folder=s.get("input_folder", ""),
                       remote_device=info.get("device_name") or {"cuda": "NVIDIA GPU", "mps": "Apple GPU", "cpu": "CPU"}.get(
                           s.get("device", ""), s.get("device", "")))
    s["host"] = f"{host} (detection run remotely from {_local_name()})"
    s["input_folder"], s["output_folder"] = str(folder), str(out)
    sp.write_text(json.dumps(s, indent=1, default=str))
    df = pd.read_csv(out / "results.csv", dtype={"well": str})
    if prev is not None:
        from .review import carry_human
        df = carry_human(prev, df)
    RP.write_tables(out, df)
    RP.build_report(out)
    try:
        LIB.register(out)
        LIB.snapshot(out, "detected")
    except Exception:
        pass


def _local_name() -> str:
    import platform
    return f"{platform.node()} ({platform.system()})"


# ---------------------------------------------------------------- install KidneyCyst on the other computer
INSTALL_STATE = dict(running=False, done=False, ok=False, step="", lines=[], error="", xfer=0, xfer_total=0, result=None)


class _InstallJob:                                  # what _Counting updates while the program is copied
    def __init__(self, st):
        self.st = st

    @property
    def xfer(self):
        return self.st["xfer"]

    @xfer.setter
    def xfer(self, v):
        self.st["xfer"] = v


def start_install(host: str) -> dict:
    st = INSTALL_STATE
    if st["running"]:
        return dict(ok=False, error="An installation is already running.")
    host = _check_host(host)
    st.update(running=True, done=False, ok=False, step="Checking the other computer…", lines=[], error="", xfer=0,
              xfer_total=0, result=None, host=host)
    threading.Thread(target=_install, args=(host,), daemon=True).start()
    return dict(ok=True)


def _say(line: str):
    INSTALL_STATE["lines"] = (INSTALL_STATE["lines"] + [line.rstrip()])[-200:]


def _install(host: str):
    st = INSTALL_STATE
    try:
        from .qupath_io import install_home
        home = install_home()
        if home is None or not (home / "model" / "plans.json").exists() or not list((home / "app").glob("kidneycyst-*.whl")):
            raise RemoteError("This copy of KidneyCyst was not started from an installation, so there is nothing to copy. "
                              "Install KidneyCyst on the other computer by hand.")
        # 1. check: system, free space, and that ~/KidneyCyst/files is ours (or absent)
        r = _run(host, _sh(f"uname -s; uname -m; df -Pk ~ | awk 'NR==2{{print $4}}'; "
                           f"if [ -e {REMOTE_HOME} ]; then if [ -e {REMOTE_HOME}/files/model/plans.json ] || "
                           f"[ -e {REMOTE_HOME}/files/env ] || [ -e {REMOTE_HOME}/.kidneycyst-remote ]; then echo OURS; "
                           f"else echo OTHER; fi; else echo NONE; fi; "
                           f"command -v curl >/dev/null && echo CURL; command -v wget >/dev/null && echo WGET; "
                           f"command -v uv >/dev/null && echo HASUV; command -v sbatch >/dev/null && echo SLURM; "
                           f"nvidia-smi -L >/dev/null 2>&1 && echo GPU"), timeout=60)
        out = r.stdout.split()
        if len(out) < 4:
            raise RemoteError(explain(r.stderr, host))
        system, free_kb, there = out[0], int(out[2]) if out[2].isdigit() else 0, out[3]
        if system not in ("Linux", "Darwin"):
            raise RemoteError(f"{host} runs {system}; automatic installation works only on Linux and macOS.")
        if there == "OTHER":
            raise RemoteError(f"{host} already has a folder {REMOTE_HOME} that was not made by KidneyCyst. "
                              f"Rename or remove it there, then try again.")
        if free_kb < 8e6:
            raise RemoteError(f"Your home folder on {host} has only {free_kb / 1e6:.1f} GB free; the installation needs "
                              f"about 8 GB.")
        if "HASUV" not in out and "CURL" not in out and "WGET" not in out:
            raise RemoteError(f"{host} has neither curl nor wget, so the installer tool cannot be downloaded there.")
        _say(f"{host}: {system} {out[1]}, {free_kb / 1e6:.0f} GB free in the home folder.")
        # 2. copy the program and the model from this installation
        src = [home / "app", home / "model"]
        st["xfer_total"] = sum(f.stat().st_size for d in src for f in d.rglob("*") if f.is_file())
        st["step"] = f"Copying the program and model to {host}…"
        _say(f"Copying {st['xfer_total'] / 1e6:.0f} MB (program and model)…")
        p = _popen(host, _sh(f"mkdir -p {REMOTE_HOME}/files && touch {REMOTE_HOME}/.kidneycyst-remote && rm -rf {REMOTE_HOME}/files/app {REMOTE_HOME}/files/model "
                             f"&& tar -xf - -C {REMOTE_HOME}/files"),
                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=_Counting(p.stdin, _InstallJob(st)), mode="w|", format=tarfile.PAX_FORMAT) as t:
                for d in src:
                    t.add(d, arcname=d.name)
            p.stdin.close()
        except OSError:
            pass
        if p.wait() != 0:
            raise RemoteError("Copying failed: " + explain(p.stderr.read().decode(errors="replace"), host))
        # 3. Python + PyTorch + KidneyCyst, downloaded on the other computer
        # A cluster login node has no graphics card, so uv cannot see which PyTorch the GPU nodes need: use CUDA 12.8 there.
        tb = "auto" if ("GPU" in out or "SLURM" not in out) else "cu128"
        get = "curl -LsSf" if "CURL" in out else "wget -qO-"
        script = f"""set -e
H={REMOTE_HOME}; F=$H/files
export UV_CACHE_DIR=$H/.uv-cache UV_PYTHON_INSTALL_DIR=$H/.python
UV=$(command -v uv || true)
if [ -z "$UV" ]; then
  echo "KCSTEP Downloading the installer tool"
  {get} https://astral.sh/uv/{UV_VERSION}/install.sh | env UV_INSTALL_DIR=$F/tools UV_NO_MODIFY_PATH=1 sh
  UV=$F/tools/uv
fi
echo "KCSTEP Creating a Python environment"
"$UV" venv "$F/env" --python 3.12 --clear
echo "KCSTEP Downloading and installing PyTorch (the largest step)"
"$UV" pip install --python "$F/env/bin/python" 'torch!=2.9.*' --torch-backend={tb}
echo "KCSTEP Installing KidneyCyst"
"$UV" pip install --python "$F/env/bin/python" -r "$F/app/requirements.txt" "$F"/app/kidneycyst-*.whl
rm -rf "$UV_CACHE_DIR"
echo "KCSTEP Checking the installation"
"$F/env/bin/python" -m kidneycyst.cli info --no-device | grep -q '^KIDNEYCYST_INFO '
echo KCDONE
"""
        p = _popen(host, _sh(script), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   text=True, bufsize=1, encoding="utf-8", errors="replace")
        done = False
        for line in p.stdout:
            if line.startswith("KCSTEP "):
                st["step"] = line[7:].strip() + "…"
            elif line.startswith("KCDONE"):
                done = True
            _say(line)
        if p.wait() != 0 or not done:
            tail = [l for l in st["lines"] if l.strip()][-1:] or ["no message"]
            hint = " (does it have internet access?)" if any("download" in l.lower() or "connect" in l.lower()
                                                              for l in st["lines"][-5:]) else ""
            raise RemoteError(f"Installing on {host} stopped during: {st['step'].rstrip('…')}{hint}. Last line: {tail[0]}")
        st["step"] = "Installed. Testing the connection again…"
        st["result"] = probe(host, f"{REMOTE_HOME}/files/env/bin/python -m kidneycyst.cli")
        st["ok"] = bool(st["result"]["ok"])
        if st["ok"]:
            r = st["result"]
            save_settings(host=host, command=r["command"], info=r["info"], slurm=r["slurm"], partitions=r["partitions"])
    except RemoteError as e:
        st["error"] = str(e)
    except Exception as e:
        st["error"] = f"{type(e).__name__}: {e}"
    finally:
        st.update(running=False, done=True)
