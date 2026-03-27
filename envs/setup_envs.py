"""
setup_envs.py — создаёт изолированные виртуальные окружения для каждой модели/решения.

Использование:
  python envs/setup_envs.py              # создать все окружения (CPU build)
  python envs/setup_envs.py --cuda       # M3_translategemma собирается с CUDA
  python envs/setup_envs.py R1_argos     # только одно окружение
  python envs/setup_envs.py --list       # список окружений и статус

После установки каждого окружения создаётся requirements.lock с точными версиями.

Структура:
  envs/<name>/requirements.txt   — входные зависимости (с пин-версиями)
  envs/<name>/venv/              — виртуальное окружение (в .gitignore)
  envs/<name>/requirements.lock  — заморозка после установки
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path

ENVS_DIR = Path(__file__).parent
PYTHON = sys.executable  # тот же интерпретатор, которым запущен скрипт

# Для M3 (llama-cpp-python) с CUDA нужна переменная окружения
CUDA_ENV = {**os.environ, "CMAKE_ARGS": "-DGGML_CUDA=on"}


def run(cmd: list, env=None, cwd=None) -> int:
    """Запускает команду, выводит вывод в реальном времени."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=cwd,
    )
    for line in proc.stdout:
        print(line, end="")
    proc.wait()
    return proc.returncode


def create_venv(env_dir: Path) -> Path:
    venv_path = env_dir / "venv"
    if venv_path.exists():
        print(f"  [skip] venv already exists: {venv_path}")
        return venv_path
    print(f"  Creating venv: {venv_path}")
    rc = run([PYTHON, "-m", "venv", str(venv_path)])
    if rc != 0:
        raise RuntimeError(f"venv creation failed (exit {rc})")
    return venv_path


def get_pip(venv_path: Path) -> str:
    """Путь к pip внутри venv."""
    if sys.platform == "win32":
        return str(venv_path / "Scripts" / "pip.exe")
    return str(venv_path / "bin" / "pip")


def get_python(venv_path: Path) -> str:
    if sys.platform == "win32":
        return str(venv_path / "Scripts" / "python.exe")
    return str(venv_path / "bin" / "python")


def install_requirements(env_dir: Path, venv_path: Path, use_cuda: bool = False):
    req_file = env_dir / "requirements.txt"
    if not req_file.exists():
        print(f"  [skip] no requirements.txt in {env_dir}")
        return

    pip = get_pip(venv_path)

    # Upgrade pip first
    print("  Upgrading pip...")
    run([pip, "install", "--upgrade", "pip", "--quiet"])

    env_name = env_dir.name
    if env_name == "M3_translategemma" and use_cuda:
        # llama-cpp-python требует специальной сборки с CUDA
        print("  [CUDA build] Installing llama-cpp-python with CUDA support...")
        # Сначала ставим всё остальное из requirements.txt кроме llama-cpp-python
        lines = req_file.read_text(encoding="utf-8").splitlines()
        other_pkgs = [
            l.strip() for l in lines
            if l.strip() and not l.startswith("#") and "llama-cpp-python" not in l
        ]
        if other_pkgs:
            run([pip, "install"] + other_pkgs)
        # Затем собираем llama-cpp-python с CUDA
        rc = run(
            [pip, "install", "llama-cpp-python==0.3.19",
             "--force-reinstall", "--no-cache-dir"],
            env=CUDA_ENV
        )
        if rc != 0:
            print("  [WARN] CUDA build failed, falling back to CPU build...")
            run([pip, "install", "llama-cpp-python==0.3.19"])
    else:
        print(f"  Installing from {req_file.name}...")
        rc = run([pip, "install", "-r", str(req_file)])
        if rc != 0:
            raise RuntimeError(f"pip install failed (exit {rc})")


def freeze(env_dir: Path, venv_path: Path):
    pip = get_pip(venv_path)
    lock_file = env_dir / "requirements.lock"
    result = subprocess.run(
        [pip, "freeze"],
        capture_output=True, text=True, encoding="utf-8"
    )
    lock_file.write_text(result.stdout, encoding="utf-8")
    print(f"  Frozen -> {lock_file.name} ({len(result.stdout.splitlines())} packages)")


def setup_env(env_dir: Path, use_cuda: bool = False):
    print(f"\n{'='*60}")
    print(f"  Setting up: {env_dir.name}")
    print(f"{'='*60}")
    try:
        venv_path = create_venv(env_dir)
        install_requirements(env_dir, venv_path, use_cuda=use_cuda)
        freeze(env_dir, venv_path)
        print(f"  [OK] {env_dir.name}")
    except Exception as e:
        print(f"  [ERROR] {env_dir.name}: {e}")


def list_envs():
    print("\nEnvironments in envs/:\n")
    print(f"  {'Name':<25} {'requirements.txt':<10} {'venv':<10} {'requirements.lock':<10}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
    for env_dir in sorted(ENVS_DIR.iterdir()):
        if not env_dir.is_dir() or env_dir.name.startswith("."):
            continue
        has_req = (env_dir / "requirements.txt").exists()
        has_venv = (env_dir / "venv").exists()
        has_lock = (env_dir / "requirements.lock").exists()
        print(f"  {env_dir.name:<25} {'yes' if has_req else 'no':<10} "
              f"{'yes' if has_venv else 'no':<10} {'yes' if has_lock else 'no':<10}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Setup isolated environments for each model/solution.")
    parser.add_argument("envs", nargs="*", help="Specific env names to setup (default: all)")
    parser.add_argument("--cuda", action="store_true",
                        help="Build M3_translategemma with CUDA support")
    parser.add_argument("--list", action="store_true", help="List envs and their status")
    args = parser.parse_args()

    if args.list:
        list_envs()
        return

    # Определяем какие окружения создавать
    all_env_dirs = sorted(
        d for d in ENVS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and (d / "requirements.txt").exists()
    )

    if args.envs:
        target_dirs = []
        for name in args.envs:
            match = [d for d in all_env_dirs if d.name == name]
            if not match:
                print(f"[WARN] Unknown env: {name}")
            else:
                target_dirs.extend(match)
    else:
        target_dirs = all_env_dirs

    if not target_dirs:
        print("No environments to set up.")
        return

    print(f"\nWill setup {len(target_dirs)} environment(s):")
    for d in target_dirs:
        print(f"  - {d.name}")
    if args.cuda:
        print("  [CUDA mode ON for M3_translategemma]")

    for env_dir in target_dirs:
        setup_env(env_dir, use_cuda=args.cuda)

    print("\n\nDone. Summary:")
    list_envs()


if __name__ == "__main__":
    main()
