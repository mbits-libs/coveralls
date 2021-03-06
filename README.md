# coveralls
Coverage gathering, with optional uploading to Coveralls.

## Requirements

### Python

Works with CPython 2.7 and 3.6.

### GCC

Currently, only GCC/gcov is supported. An effort to support llvm-cov was made, but nothing working is yet available.

### cURL

Curl is used to upload the JSON to Coveralls site. Needed only, if configured with upload support.


## Usage

The tool contains a CMake script for easy configuration. Provided the tool was added as a submodule under `tools`, you should add something like this to the root CMakeLists.txt:

```cmake
find_package(Python3 COMPONENTS Interpreter REQUIRED)

foreach(MOD one two three)
  list(APPEND COVERALLS_DIRS
    libs/lib${MOD}/include/${MOD}
    libs/lib${MOD}/src)
endforeach()

include(tools/coveralls/Coveralls.cmake)

if (COVERALLS AND NOT ???_TESTING)
  message(FATAL_ERROR "Coveralls are useless without -D???_TESTING=ON")
endif()
```

### Generating

When properly configured, call the build system with the `coveralls` target, either

```shell
make -j`nproc` && make coveralls
```

or

```shell
ninja && ninja coveralls
```

### Options

There are two options introduced by the script.

**COVERALLS** turns on coveralls support and allows to use the targets defined in the script. **OFF** by default.

**COVERALLS_UPLOAD** creates a target, which will upload the generated JSON to Coveralls site. **OFF** by default, but used only when `COVERALLS` is `ON` as well.

By default, no Coveralls targets are available. When building, e.g. on Travis CI, cmake should be configured with

```shell
[...] -DCOVERALLS=ON -DCOVERALLS_UPLOAD=ON [...]
```

When building for local analysis of coverage (e.g. to use with `get_cover.py`), upload may be turned off with either:

```shell
[...] -DCOVERALLS=ON [...]
```

or more explicit:

```shell
[...] -DCOVERALLS=ON -DCOVERALLS_UPLOAD=OFF [...]
```

### Targets

| Target | Depends On | Comment |
| ------ | ---------- | ------- |
| `coveralls` | `coveralls_upload` or `coveralls_generate` | Will depend on `coveralls_upload` only, if `COVERALLS_UPLOAD` option is set to `ON`. |
| `coveralls_upload` | `coveralls_generate` | Present only, if  `COVERALLS_UPLOAD` option is set to `ON`. |
| `coveralls_generate` | `coveralls_test` | Will use the counters generated by tests to produce the Coveralls JSON |
| `coveralls_test` | `coveralls_prepare` | Runs the tests through `${CMAKE_CTEST_COMMAND}`. |
| `coveralls_prepare` (Windows) |  | Does nothing |
| `coveralls_prepare` (UNIX) | `coveralls_clean_counters` and `coveralls_remove_intermediate_files` | Calls counter cleanup. |
| `coveralls_clean_counters` |  | Cleans all the GCDA files from build directory. |
| `coveralls_remove_intermediate_files` |  | Removes and re-creates the `gcov` subdirectory of the build directory. This directory is used during `coveralls_generate` to store intermediate files. |
