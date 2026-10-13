cmake_minimum_required(VERSION 3.18)
project(pulseq_cpp_siemens LANGUAGES CXX)

# The C++ reader: ExternalSequence of pulseq/pulseq (MIT) at one commit. pulseq-reader.sha256
# names the commit, the files and the SHA-256 of each. The build takes the files from the first
# of:
#   1. the environment variable PULSEQ_SOURCE_DIR: a checkout of pulseq/pulseq (the Nix devShell
#      sets it to the store path that flake.nix fetches);
#   2. third_party/pulseq/ next to this file: the copy that the sdist carries
#      (scripts/fetch_reader.py puts it there);
#   3. raw.githubusercontent.com at the commit, unless PULSEQ_ALLOW_DOWNLOAD is OFF.
# Each file must have its SHA-256, whichever the source, so the three give the same bytes.
option(PULSEQ_ALLOW_DOWNLOAD "Download the reader's files when no copy is found" ON)

file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/pulseq-reader.sha256" PULSEQ_COMMIT_LINE
     REGEX "^# commit [0-9a-f]+$")
string(REGEX REPLACE "^# commit " "" PULSEQ_COMMIT "${PULSEQ_COMMIT_LINE}")
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/pulseq-reader.sha256" PULSEQ_FILES
     REGEX "^[0-9a-f]+  ")
if(NOT PULSEQ_COMMIT MATCHES "^[0-9a-f]+$" OR NOT PULSEQ_FILES)
  message(FATAL_ERROR "pulseq-reader.sha256 names no commit or no file")
endif()

if(DEFINED ENV{PULSEQ_SOURCE_DIR})
  set(PULSEQ_DIR "$ENV{PULSEQ_SOURCE_DIR}")
  set(PULSEQ_FROM "PULSEQ_SOURCE_DIR")
elseif(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/third_party/pulseq/src/ExternalSequence.cpp")
  set(PULSEQ_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/pulseq")
  set(PULSEQ_FROM "third_party/pulseq")
elseif(PULSEQ_ALLOW_DOWNLOAD)
  set(PULSEQ_DIR "${CMAKE_BINARY_DIR}/pulseq")
  set(PULSEQ_FROM "raw.githubusercontent.com")
else()
  message(FATAL_ERROR "The files of pulseq/pulseq ${PULSEQ_COMMIT} are not in "
                      "PULSEQ_SOURCE_DIR or third_party/pulseq, and PULSEQ_ALLOW_DOWNLOAD is OFF")
endif()

foreach(entry IN LISTS PULSEQ_FILES)
  string(REGEX REPLACE "^([0-9a-f]+)  (.*)$" "\\1;\\2" parts "${entry}")
  list(GET parts 0 sha256)
  list(GET parts 1 name)
  if(PULSEQ_FROM STREQUAL "raw.githubusercontent.com" AND NOT EXISTS "${PULSEQ_DIR}/${name}")
    file(DOWNLOAD
         "https://raw.githubusercontent.com/pulseq/pulseq/${PULSEQ_COMMIT}/${name}"
         "${PULSEQ_DIR}/${name}"
         EXPECTED_HASH SHA256=${sha256} STATUS status)
    list(GET status 0 code)
    if(NOT code EQUAL 0)
      message(FATAL_ERROR "Download of pulseq/pulseq ${name} failed: ${status}")
    endif()
  endif()
  if(NOT EXISTS "${PULSEQ_DIR}/${name}")
    message(FATAL_ERROR "${PULSEQ_DIR}/${name} (from ${PULSEQ_FROM}) does not exist")
  endif()
  file(SHA256 "${PULSEQ_DIR}/${name}" actual)
  if(NOT actual STREQUAL sha256)
    message(FATAL_ERROR "${PULSEQ_DIR}/${name} (from ${PULSEQ_FROM}) is not the file of "
                        "pulseq/pulseq ${PULSEQ_COMMIT}: SHA-256 ${actual}, expected ${sha256}")
  endif()
endforeach()
# The copy of the licence that the wheel's metadata names must be the licence of the commit.
file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE.pulseq" actual)
file(SHA256 "${PULSEQ_DIR}/LICENSE" expected)
if(NOT actual STREQUAL expected)
  message(FATAL_ERROR "LICENSE.pulseq is not the LICENSE of pulseq/pulseq ${PULSEQ_COMMIT}")
endif()
message(STATUS "pulseq/pulseq ${PULSEQ_COMMIT} from ${PULSEQ_FROM}: ${PULSEQ_DIR}")

# The reader as its own library: it uses std::bind1st, which C++17 removed, so it keeps C++11
# (MSVC has no mode below C++14, which still has std::bind1st). nanobind needs C++17.
add_library(pulseq_reader STATIC
            "${PULSEQ_DIR}/src/ExternalSequence.cpp" "${PULSEQ_DIR}/src/md5.cpp")
target_include_directories(pulseq_reader PUBLIC "${PULSEQ_DIR}/src")
set_target_properties(pulseq_reader PROPERTIES
                      CXX_STANDARD 11 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF
                      POSITION_INDEPENDENT_CODE ON)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  # ExternalSequence::getline compares a char with EOF. Where char is unsigned (gcc on Linux
  # aarch64) the comparison is never true and the reader does not end on any file; the
  # reader of the scanner (x86_64) has a signed char.
  # The x86_64 build has no FMA instructions, so it never fuses a multiply and an add; a build
  # for arm64 would fuse them unless told not to, and round some values differently.
  target_compile_options(pulseq_reader PRIVATE -fsigned-char -ffp-contract=off -w)
elseif(MSVC)
  target_compile_options(pulseq_reader PRIVATE /fp:precise /W0)
  target_compile_definitions(pulseq_reader PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
# The reader keeps its assert() calls, as the driver of the C++ oracle does (it is built
# without NDEBUG). A failed assert would end the Python process, so the extension never calls a
# function that asserts: GetAllDefinitions is not called (it reads the definitions itself), and
# decodeBlock's assert on the version cannot fail after the version gate.
target_compile_options(pulseq_reader PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/UNDEBUG>)
target_compile_options(pulseq_reader PRIVATE $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-UNDEBUG>)

# SKBUILD_SABI_COMPONENT is Development.SABIModule when wheel.py-api asks for the stable ABI:
# without it nanobind builds for one Python version only, under a wheel tagged abi3.
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module
             ${SKBUILD_SABI_COMPONENT})
find_package(nanobind CONFIG REQUIRED)
nanobind_add_module(_reader NB_STATIC STABLE_ABI src/reader.cpp)
target_link_libraries(_reader PRIVATE pulseq_reader)
target_compile_definitions(_reader PRIVATE PULSEQ_COMMIT="${PULSEQ_COMMIT}")
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  # The extension reads the version with the reader's own code (the version gate), so it has
  # the reader's char and arithmetic too.
  target_compile_options(_reader PRIVATE -fsigned-char -ffp-contract=off)
elseif(MSVC)
  target_compile_options(_reader PRIVATE /fp:precise)
endif()
install(TARGETS _reader LIBRARY DESTINATION pulseq_cpp_siemens)
