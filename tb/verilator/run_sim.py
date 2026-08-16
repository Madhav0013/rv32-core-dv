#!/usr/bin/env python3
import argparse
import os
import subprocess

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--elf', required=True)
    parser.add_argument('--signature', required=True)
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    cocotb_dir = os.path.join(repo_root, 'tb', 'cocotb')

    env = os.environ.copy()
    env['TESTCASE_ELF'] = os.path.abspath(args.elf)
    env['SIGNATURE_FILE'] = os.path.abspath(args.signature)

    test_name = os.path.basename(os.path.dirname(os.path.dirname(args.elf)))
    sim_build_dir = f'sim_build/soc_top_{test_name}'
    env['COCOTB_RESULTS_FILE'] = os.path.abspath(os.path.join(cocotb_dir, sim_build_dir, 'results.xml'))
    cmd = ['make', 'soc_top', f'SOC_TOP_SIM_BUILD={sim_build_dir}']
    # We suppress output to avoid spamming unless it fails
    try:
        subprocess.run(cmd, env=env, cwd=cocotb_dir, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Simulation failed for {args.elf}")
        print(e.stdout)
        print(e.stderr)
        raise

if __name__ == '__main__':
    main()
