"""Execute the maintained scanner's actual loop with syscall/Foundation doubles.

No iOS runtime or private locking behavior is simulated. Only the enumeration
control flow is under test. Four Foundation expressions are replaced explicitly;
the loop, branches, continue statements, syscall and path-length checks are kept.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("LIVE_CONTAINER_TEST_SOURCE", ROOT)) / "LiveContainer/Tweaks/Dead10ccFix.m"


def loop(source):
    start = source.index("        uint64_t count = pidinfo_size / sizeof(struct proc_fdinfo);")
    end = source.index("    free(pidinfo);", start)
    result = source[start:end]
    # Remove the closing brace belonging to the outer pidinfo-size guard.
    assert result.endswith("    }\n")
    result = result[:-6]
    substitutions = {
        "NSString *path = [[NSFileManager defaultManager] stringWithFileSystemRepresentation:vnodeinfo.pvip.vip_path length:pathlen];":
            "const char *path = make_path(vnodeinfo.pvip.vip_path, pathlen);",
        "path = [path stringByStandardizingPath];": "path = standardize(path);",
        "[openFilePaths addObject:path];": "record_path(path);",
        "path == nil": "path == NULL",
    }
    for old, new in substitutions.items():
        assert result.count(old) == 1, old
        result = result.replace(old, new)
    return result

HARNESS = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
enum { PROX_FDTYPE_VNODE = 1, PROC_PIDFDVNODEPATHINFO = 2 };
struct proc_fdinfo { int proc_fd; int proc_fdtype; };
struct vnode_fdinfowithpath { struct { char vip_path[32]; } pvip; };
static int scenario, visits[3], recorded;
static int proc_pidfdinfo(int pid, int fd, int kind, void *out, size_t size) {
    assert(pid == 123 && kind == PROC_PIDFDVNODEPATHINFO && fd >= 0 && fd < 3);
    visits[fd]++;
    struct vnode_fdinfowithpath *value = out;
    memset(value, 0, size);
    if (fd == 0) {
        if (scenario == 1) return 0;
        if (scenario == 2) return (int)size - 1;
        if (scenario == 3) return -1;
        if (scenario == 4) return (int)size;
        if (scenario == 5) { strcpy(value->pvip.vip_path, "invalid"); return (int)size; }
    }
    strcpy(value->pvip.vip_path, fd == 0 ? "first" : fd == 1 ? "second" : "third");
    return (int)size;
}
static const char *make_path(const char *path, int64_t length) {
    assert(length > 0); return strcmp(path, "invalid") ? path : NULL;
}
static const char *standardize(const char *path) { return path; }
static void record_path(const char *path) {
    if (!strcmp(path, "first")) recorded |= 1;
    if (!strcmp(path, "second")) recorded |= 2;
    if (!strcmp(path, "third")) recorded |= 4;
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = atoi(argv[1]);
    struct proc_fdinfo entries[] = {{0, PROX_FDTYPE_VNODE}, {1, PROX_FDTYPE_VNODE}, {2, PROX_FDTYPE_VNODE}};
    if (scenario == 6) entries[0].proc_fdtype = 99;
    void *pidinfo = entries; int pidinfo_size = sizeof(entries), pid = 123;
__LOOP__
    int expected = scenario == 0 ? 7 : 6;
    if (recorded != expected || visits[1] != 1 || visits[2] != 1 || visits[0] != (scenario == 6 ? 0 : 1)) return 17;
    return 0;
}
'''


class Dead10ccScanProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc") or shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("C compiler unavailable")
        cls.source = SOURCE.read_text()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binaries = {}
        current = loop(cls.source)
        assert current.count("for (; count--; fdinfo++) {") == 1
        baseline = current.replace("for (; count--; fdinfo++) {", "while (count--) {")
        end = baseline.rfind("        }\n")
        baseline = baseline[:end] + "            fdinfo++;\n" + baseline[end:]
        for label, block in (("current", current), ("baseline", baseline)):
            cfile = Path(cls.temp.name) / (label + ".c")
            binary = Path(cls.temp.name) / label
            cfile.write_text(HARNESS.replace("__LOOP__", block))
            built = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare", str(cfile), "-o", str(binary)], capture_output=True, text=True)
            if built.returncode: raise AssertionError(built.stderr)
            cls.binaries[label] = binary

    def scenario(self, number, old_fails=True):
        for label, expected in (("baseline", 17 if old_fails else 0), ("current", 0)):
            result = subprocess.run([str(self.binaries[label]), str(number)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, expected, label + result.stderr)

    def test_lookup_failure_advances(self): self.scenario(1)
    def test_short_lookup_advances(self): self.scenario(2)
    def test_negative_lookup_advances(self): self.scenario(3)
    def test_empty_path_advances(self): self.scenario(4)
    def test_failed_path_conversion_advances(self): self.scenario(5)
    def test_non_vnode_advances(self): self.scenario(6, False)
    def test_success_enumerates_every_entry_once(self): self.scenario(0, False)


if __name__ == "__main__": unittest.main()
