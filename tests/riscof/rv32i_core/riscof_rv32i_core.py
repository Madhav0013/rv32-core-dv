import os
import re
import shutil
import subprocess
import shlex
import logging
import random
import string
from string import Template
import sys

import riscof.utils as utils
import riscof.constants as constants
from riscof.pluginTemplate import pluginTemplate

logger = logging.getLogger()

class rv32i_core(pluginTemplate):
    __model__ = "rv32i_core"

    #TODO: please update the below to indicate family, version, etc of your DUT.
    __version__ = "XXX"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        config = kwargs.get('config')

        # If the config node for this DUT is missing or empty. Raise an error. At minimum we need
        # the paths to the ispec and pspec files
        if config is None:
            print("Please enter input file paths in configuration.")
            raise SystemExit(1)

        # In case of an RTL based DUT, this would be point to the final binary executable of your
        # test-bench produced by a simulator (like verilator, vcs, incisive, etc). In case of an iss or
        # emulator, this variable could point to where the iss binary is located. If 'PATH variable
        # is missing in the config.ini we can hardcode the alternate here.
        self.dut_exe = os.path.join(config['PATH'] if 'PATH' in config else "","rv32i_core")

        # Number of parallel jobs that can be spawned off by RISCOF
        # for various actions performed in later functions, specifically to run the tests in
        # parallel on the DUT executable. Can also be used in the build function if required.
        self.num_jobs = str(config['jobs'] if 'jobs' in config else 1)

        # Path to the directory where this python file is located. Collect it from the config.ini
        self.pluginpath=os.path.abspath(config['pluginpath'])

        # Collect the paths to the  riscv-config absed ISA and platform yaml files. One can choose
        # to hardcode these here itself instead of picking it from the config.ini file.
        self.isa_spec = os.path.abspath(config['ispec'])
        self.platform_spec = os.path.abspath(config['pspec'])

        #We capture if the user would like the run the tests on the target or
        #not. If you are interested in just compiling the tests and not running
        #them on the target, then following variable should be set to False
        if 'target_run' in config and config['target_run']=='0':
            self.target_run = False
        else:
            self.target_run = True

    def initialise(self, suite, work_dir, archtest_env):

       # capture the working directory. Any artifacts that the DUT creates should be placed in this
       # directory. Other artifacts from the framework and the Reference plugin will also be placed
       # here itself.
       self.work_dir = work_dir

       # capture the architectural test-suite directory.
       self.suite_dir = suite

       # Note the march is not hardwired here, because it will change for each
       # test. Similarly the output elf name and compile macros will be assigned later in the
       # runTests function
       self.compile_cmd = 'riscv-none-elf-gcc \
         -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles -g\
         -T '+self.pluginpath+'/env/link.ld\
         -I '+self.pluginpath+'/env/\
         -I ' + archtest_env

       # add more utility snippets here

    def build(self, isa_yaml, platform_yaml):

      # load the isa yaml as a dictionary in python.
      ispec = utils.load_yaml(isa_yaml)['hart0']

      # capture the XLEN value by picking the max value in 'supported_xlen' field of isa yaml. This
      # will be useful in setting integer value in the compiler string (if not already hardcoded);
      self.xlen = ('64' if 64 in ispec['supported_xlen'] else '32')

      # for rv32i_core start building the '--isa' argument. the self.isa is dutnmae specific and may not be
      # useful for all DUTs
      self.isa = 'rv' + self.xlen
      if "I" in ispec["ISA"]:
          self.isa += 'i'
      if "M" in ispec["ISA"]:
          self.isa += 'm'
      if "F" in ispec["ISA"]:
          self.isa += 'f'
      if "D" in ispec["ISA"]:
          self.isa += 'd'
      if "C" in ispec["ISA"]:
          self.isa += 'c'

      #TODO: The following assumes you are using the riscv-gcc toolchain. If
      #      not please change appropriately
      self.compile_cmd = self.compile_cmd+' -mabi='+('lp64 ' if 64 in ispec['supported_xlen'] else 'ilp32 ')

    def runTests(self, testList):
        for testname in testList:
            testentry = testList[testname]
            test      = testentry['test_path']
            test_dir  = testentry['work_dir']
            elf       = os.path.join(test_dir, 'dut.elf')
            sig_file  = os.path.join(test_dir, self.name[:-1] + ".signature")

            macros = ""
            for m in testentry['macros']:
                macros += f" -D{m}"

            # 1. compile
            compile_cmd = (
                f'{self.compile_cmd} -march={testentry["isa"].lower()} '
                f'{macros} {test} -o {elf}'
            )
            utils.shellCommand(compile_cmd).run(cwd=test_dir)

            if self.target_run:
                # 2. simulate on the RTL, dumping the signature region
                repo_root = os.path.abspath(os.path.join(self.pluginpath, '..', '..', '..'))
                sim_cmd = (
                    f'python3 {repo_root}/tb/verilator/run_sim.py '
                    f'--elf {elf} --signature {sig_file}'
                )
                utils.shellCommand(sim_cmd).run(cwd=test_dir)
