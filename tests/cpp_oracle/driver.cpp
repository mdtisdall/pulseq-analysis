// Reads the .seq file that the argument names with ExternalSequence::load of pulseq/pulseq
// (the reader of the scanner), then decodes each block with decodeBlock, and says whether both
// succeed.
//
// Exit status: 0 when the file loads and each block decodes; 1 when it does not load, when a
// block does not decode, or when the reader throws; 2 for a wrong call; 70 when the process
// receives SIGSEGV, SIGABRT, SIGFPE, SIGILL, SIGBUS or SIGTRAP. The messages of the reader go to
// stderr, so a caller gets the reason.
#include <csignal>
#include <cstdio>
#include <exception>
#include <string>
#include <unistd.h>

#include "ExternalSequence.h"

static void print_to_stderr(const std::string& message) {
    fprintf(stderr, "%s\n", message.c_str());
}

// write and _exit are safe in a signal handler; fprintf is not.
static void on_crash(int) {
    const char text[] = "pulseq-cpp-oracle: crash in ExternalSequence\n";
    if (write(STDERR_FILENO, text, sizeof text - 1) < 0) {
        // Nothing to do: the process ends in the next line.
    }
    _exit(70);
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s file.seq\n", argv[0]);
        return 2;
    }
    for (int signal_number : {SIGSEGV, SIGABRT, SIGFPE, SIGILL, SIGBUS, SIGTRAP}) {
        signal(signal_number, on_crash);
    }
    ExternalSequence::SetPrintFunction(&print_to_stderr);
    try {
        ExternalSequence sequence;
        if (!sequence.load(argv[1])) {
            fprintf(stderr, "pulseq-cpp-oracle: ExternalSequence::load returned false\n");
            return 1;
        }
        int failed = 0;
        for (int block = 0; block < sequence.GetNumberOfBlocks(); block++) {
            SeqBlock* seq_block = sequence.GetBlock(block);
            if (!sequence.decodeBlock(seq_block)) {
                fprintf(stderr, "pulseq-cpp-oracle: decodeBlock returned false for block %d\n",
                        block);
                failed++;
            }
            delete seq_block;
        }
        if (failed > 0) {
            return 1;
        }
    } catch (const std::exception& error) {
        fprintf(stderr, "pulseq-cpp-oracle: exception: %s\n", error.what());
        return 1;
    }
    return 0;
}
