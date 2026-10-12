// Reads the .seq file that the argument names with ExternalSequence::load of pulseq/pulseq
// (the reader of the scanner), then decodes each block with decodeBlock. It has three modes:
//
//   driver FILE            says whether the file loads and each block decodes (exit status only)
//   driver --dump FILE     writes what the reader holds after load and decodeBlock as one JSON
//                          object on stdout
//   driver --sample FILE   reads lines "block_index time_us" on stdin and writes the three
//                          gradient values of SeqBlock::gradientsAt for each line
//
// Exit status: 0 when the file loads and each block decodes (and the mode did its work); 1 when
// it does not load, when a block does not decode, or when the reader throws; 2 for a wrong call
// (also a bad line on stdin in --sample); 70 when the process receives SIGSEGV, SIGABRT, SIGFPE,
// SIGILL, SIGBUS or SIGTRAP. The messages of the reader go to stderr, so a caller gets the
#include <cctype>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <map>
#include <string>
#include <vector>
#include <unistd.h>

#include "ExternalSequence.h"

// The messages of the reader go to stderr, except while --sample calls gradientsAt: on a ramp
// down it prints a message for each call, and a caller that asks for many times would drown in
// them. The messages of load and decodeBlock stay.
static bool g_silent = false;

static void print_to_stderr(const std::string& message) {
    if (!g_silent) {
        fprintf(stderr, "%s\n", message.c_str());
    }
}

// write and _exit are safe in a signal handler; fprintf is not.
static void on_crash(int) {
    const char text[] = "pulseq-cpp-oracle: crash in ExternalSequence\n";
    if (write(STDERR_FILENO, text, sizeof text - 1) < 0) {
        // Nothing to do: the process ends in the next line.
    }
    _exit(70);
}

// ---- JSON, with the standard library only. Each function returns the text of one value. ----

static std::string json_number(double value, const char* format) {
    // JSON has no NaN and no infinity: they become null.
    if (!std::isfinite(value)) {
        return "null";
    }
    char buffer[64];
    snprintf(buffer, sizeof buffer, format, value);
    return buffer;
}

// A float is written with 9 significant digits and a double with 17: each reads back exactly.
static std::string json_float(float value) { return json_number(value, "%.9g"); }
static std::string json_double(double value) { return json_number(value, "%.17g"); }
static std::string json_int(long value) { return std::to_string(value); }
static std::string json_bool(bool value) { return value ? "true" : "false"; }

static bool is_valid_utf8(const std::string& text) {
    size_t i = 0;
    while (i < text.size()) {
        unsigned char lead = text[i];
        size_t length;
        unsigned char low = 0x80, high = 0xBF;  // the range of the second byte
        if (lead < 0x80) {
            length = 1;
        } else if (lead >= 0xC2 && lead <= 0xDF) {
            length = 2;
        } else if (lead >= 0xE0 && lead <= 0xEF) {
            length = 3;
            if (lead == 0xE0) low = 0xA0;
            if (lead == 0xED) high = 0x9F;  // no surrogates
        } else if (lead >= 0xF0 && lead <= 0xF4) {
            length = 4;
            if (lead == 0xF0) low = 0x90;
            if (lead == 0xF4) high = 0x8F;
        } else {
            return false;
        }
        if (i + length > text.size()) {
            return false;
        }
        for (size_t k = 1; k < length; k++) {
            unsigned char byte = text[i + k];
            if (byte < (k == 1 ? low : 0x80) || byte > (k == 1 ? high : 0xBF)) {
                return false;
            }
        }
        i += length;
    }
    return true;
}

// Bytes below 0x20 are escaped. When the text is not valid UTF-8, each byte from 0x80 on is
// written as the code point of the same number (\u0080 to ÿ), so that the output stays
// valid JSON.
static std::string json_string(const std::string& text) {
    const bool keep_high_bytes = is_valid_utf8(text);
    std::string out = "\"";
    for (size_t i = 0; i < text.size(); i++) {
        unsigned char byte = text[i];
        if (byte == '"') {
            out += "\\\"";
        } else if (byte == '\\') {
            out += "\\\\";
        } else if (byte < 0x20 || (byte >= 0x80 && !keep_high_bytes)) {
            char escape[8];
            snprintf(escape, sizeof escape, "\\u%04x", byte);
            out += escape;
        } else {
            out += static_cast<char>(byte);
        }
    }
    return out + "\"";
}

static std::string json_floats(const std::vector<float>& values) {
    std::string out = "[";
    for (size_t i = 0; i < values.size(); i++) {
        out += (i ? "," : "") + json_float(values[i]);
    }
    return out + "]";
}

static std::string json_longs(const std::vector<long>& values) {
    std::string out = "[";
    for (size_t i = 0; i < values.size(); i++) {
        out += (i ? "," : "") + json_int(values[i]);
    }
    return out + "]";
}

// An object built key by key; the values are the texts that the functions above return.
struct JsonObject {
    std::string text = "{";
    bool empty = true;
    void add(const char* key, const std::string& value) {
        text += (empty ? "" : ",") + json_string(key) + ":" + value;
        empty = false;
    }
    std::string close() const { return text + "}"; }
};

// ---- --dump: every value is read with a public accessor of SeqBlock or ExternalSequence. ----

static std::string dump_rf(SeqBlock* block) {
    RFEvent& rf = block->GetRFEvent();
    const int length = block->GetRFLength();
    // GetRFAmplitudePtr and GetRFPhasePtr are the samples after checkRF.
    std::vector<float> magnitude, phase;
    if (length > 0) {
        magnitude.assign(block->GetRFAmplitudePtr(), block->GetRFAmplitudePtr() + length);
        phase.assign(block->GetRFPhasePtr(), block->GetRFPhasePtr() + length);
    }
    JsonObject object;
    object.add("amplitude", json_float(rf.amplitude));
    object.add("mag_shape", json_int(rf.magShape));
    object.add("phase_shape", json_int(rf.phaseShape));
    object.add("time_shape", json_int(rf.timeShape));
    object.add("shape_dur_us", json_float(rf.shape_dur));
    object.add("center_us", json_float(rf.center));
    object.add("delay_us", json_int(rf.delay));
    object.add("freq_ppm", json_float(rf.freqPPM));
    object.add("phase_ppm", json_float(rf.phasePPM));
    object.add("freq_offset", json_float(rf.freqOffset));
    object.add("phase_offset", json_float(rf.phaseOffset));
    object.add("use", json_string(std::string(1, rf.use)));
    object.add("dwell_us", json_float(block->GetRFDwellTime()));
    object.add("magnitude", json_floats(magnitude));
    object.add("phase", json_floats(phase));
    return object.close();
}

static std::string dump_gradient(SeqBlock* block, int channel) {
    const bool trap = block->isTrapGradient(channel);
    const bool ext_trap = block->isExtTrapGradient(channel);
    const bool arbitrary = block->isArbitraryGradient(channel);
    if (!trap && !ext_trap && !arbitrary) {
        return "null";
    }
    GradEvent& grad = block->GetGradEvent(channel);
    JsonObject object;
    object.add("kind", json_string(trap ? "trap" : ext_trap ? "ext_trap" : "arbitrary"));
    object.add("amplitude", json_float(grad.amplitude));
    object.add("delay_us", json_int(grad.delay));
    if (trap) {
        object.add("ramp_up_us", json_int(grad.rampUpTime));
        object.add("flat_us", json_int(grad.flatTime));
        object.add("ramp_down_us", json_int(grad.rampDownTime));
    } else if (ext_trap) {
        object.add("times_us", json_longs(block->GetExtTrapGradTimes(channel)));
        object.add("shape", json_floats(block->GetExtTrapGradShape(channel)));
    } else {
        // GetArbGradShapePtr is the samples after checkGradient. An oversampled gradient has
        // only its samples at the centres of the rasters, which is the default of the reader.
        const int length = block->GetArbGradNumSamples(channel);
        std::vector<float> samples;
        if (length > 0) {
            samples.assign(block->GetArbGradShapePtr(channel),
                           block->GetArbGradShapePtr(channel) + length);
        }
        object.add("wave_shape", json_int(grad.waveShape));
        object.add("time_shape", json_int(grad.timeShape));
        object.add("first", json_float(grad.first));
        object.add("last", json_float(grad.last));
        object.add("oversampled", json_bool(block->isArbGradWithOversampling(channel)));
        object.add("samples", json_floats(samples));
    }
    return object.close();
}

static std::string dump_adc(SeqBlock* block) {
    ADCEvent& adc = block->GetADCEvent();
    JsonObject object;
    object.add("num_samples", json_int(adc.numSamples));
    object.add("dwell_ns", json_int(adc.dwellTime));
    object.add("delay_us", json_int(adc.delay));
    object.add("freq_ppm", json_float(adc.freqPPM));
    object.add("phase_ppm", json_float(adc.phasePPM));
    object.add("freq_offset", json_float(adc.freqOffset));
    object.add("phase_offset", json_float(adc.phaseOffset));
    object.add("phase_shape", json_int(adc.phaseModulationShapeID));
    return object.close();
}

static std::string dump_trigger(SeqBlock* block) {
    TriggerEvent& trigger = block->GetTriggerEvent();
    JsonObject object;
    object.add("type", json_int(trigger.triggerType));
    object.add("channel", json_int(trigger.triggerChannel));
    object.add("delay_us", json_int(trigger.delay));
    object.add("duration_us", json_int(trigger.duration));
    return object.close();
}

static std::string dump_soft_delay(SeqBlock* block) {
    SoftDelayEvent& soft_delay = block->GetSoftDelayEvent();
    JsonObject object;
    object.add("num_id", json_int(soft_delay.numID));
    object.add("offset_us", json_int(soft_delay.offset));
    object.add("factor", json_float(soft_delay.factor));
    // The reader keeps 31 characters of the hint and ends it with a zero.
    object.add("hint", json_string(soft_delay.hint));
    return object.close();
}

// A label is known by its name (SLC, LIN, NAV, ...). A flag has the value 0 or 1.
static std::string dump_labels(ExternalSequence& sequence, std::vector<LabelEvent>& events) {
    std::string out = "[";
    for (size_t i = 0; i < events.size(); i++) {
        const LabelEvent& event = events[i];
        JsonObject object;
        if (event.flagVal.first != FLAG_UNKNOWN) {
            object.add("label", json_string(sequence.getFlagIdAsString(event.flagVal.first)));
            object.add("value", json_int(event.flagVal.second ? 1 : 0));
        } else {
            object.add("label", json_string(sequence.getCounterIdAsString(event.numVal.first)));
            object.add("value", json_int(event.numVal.second));
        }
        out += (i ? "," : "") + object.close();
    }
    return out + "]";
}

static std::string dump_rotation(SeqBlock* block) {
    const double* quaternion = block->GetRotationEvent().rotQuaternion;
    std::string out = "[";
    for (int i = 0; i < 4; i++) {
        out += (i ? "," : "") + json_double(quaternion[i]);
    }
    return out + "]";
}

static std::string dump_rf_shim(SeqBlock* block) {
    RfShimmingEvent& shim = block->GetRfShim();
    JsonObject object;
    object.add("id", json_int(shim.id));
    object.add("nchan", json_int(shim.nchan));
    object.add("amplitudes", json_floats(shim.amplitudes));
    object.add("phases", json_floats(shim.phases));
    return object.close();
}

static std::string dump_block(ExternalSequence& sequence, SeqBlock* block) {
    JsonObject object;
    object.add("index", json_int(block->GetIndex()));
    object.add("duration_ru", json_int(block->GetStoredDuration_ru()));
    object.add("rf", block->isRF() ? dump_rf(block) : "null");
    std::string grad = "[";
    for (int channel = 0; channel < NUM_GRADS; channel++) {
        grad += (channel ? "," : "") + dump_gradient(block, channel);
    }
    object.add("grad", grad + "]");
    object.add("adc", block->isADC() ? dump_adc(block) : "null");
    object.add("trigger", block->isTrigger() ? dump_trigger(block) : "null");
    object.add("soft_delay", block->isSoftDelay() ? dump_soft_delay(block) : "null");
    object.add("labelset", dump_labels(sequence, block->GetLabelSetEvents()));
    object.add("labelinc", dump_labels(sequence, block->GetLabelIncEvents()));
    object.add("rotation", block->isRotation() ? dump_rotation(block) : "null");
    object.add("rf_shim", block->hasRfShim() ? dump_rf_shim(block) : "null");
    return object.close();
}

// The JSON is written only at the end, so a failure leaves nothing on stdout.
static int run_dump(const char* path) {
    ExternalSequence sequence;
    if (!sequence.load(path)) {
        fprintf(stderr, "pulseq-cpp-oracle: ExternalSequence::load returned false\n");
        return 1;
    }
    std::string blocks = "[";
    for (int index = 0; index < sequence.GetNumberOfBlocks(); index++) {
        SeqBlock* block = sequence.GetBlock(index);
        if (!sequence.decodeBlock(block)) {
            fprintf(stderr, "pulseq-cpp-oracle: decodeBlock returned false for block %d\n", index);
            delete block;
            return 1;
        }
        blocks += (index ? "," : "") + dump_block(sequence, block);
        delete block;
    }
    blocks += "]";

    std::string definitions = "{";
    const std::vector<std::string> keys = sequence.GetAllDefinitions();
    for (size_t i = 0; i < keys.size(); i++) {
        definitions += (i ? "," : "") + json_string(keys[i]) + ":" +
                       json_string(sequence.GetDefinitionStr(keys[i]));
    }
    definitions += "}";

    JsonObject object;
    object.add("version", json_int(sequence.GetVersion()));
    object.add("definitions", definitions);
    object.add("signature_ok", json_bool(sequence.isSignatureCheckSucceeded()));
    object.add("blocks", blocks);
    const std::string text = object.close() + "\n";
    fwrite(text.data(), 1, text.size(), stdout);
    fflush(stdout);
    return 0;
}

// ---- --sample ----

// The decoded blocks, each decoded once on its first use.
struct BlockCache {
    std::map<int, SeqBlock*> blocks;
    ~BlockCache() {
        for (std::map<int, SeqBlock*>::iterator it = blocks.begin(); it != blocks.end(); ++it) {
            delete it->second;
        }
    }
};

// Reads "block_index time_us" and nothing else (spaces around the two numbers are allowed).
static bool parse_sample_line(const std::string& line, long& block_index, double& time_us) {
    const char* start = line.c_str();
    char* end = NULL;
    block_index = strtol(start, &end, 10);
    if (end == start || !isspace(static_cast<unsigned char>(*end))) {
        return false;
    }
    start = end;
    time_us = strtod(start, &end);
    if (end == start) {
        return false;
    }
    while (isspace(static_cast<unsigned char>(*end))) {
        end++;
    }
    return *end == '\0' && std::isfinite(time_us);
}

static int run_sample(const char* path) {
    ExternalSequence sequence;
    if (!sequence.load(path)) {
        fprintf(stderr, "pulseq-cpp-oracle: ExternalSequence::load returned false\n");
        return 1;
    }
    BlockCache cache;
    std::string line;
    long line_number = 0;
    while (std::getline(std::cin, line)) {
        line_number++;
        long block_index;
        double time_us;
        if (!parse_sample_line(line, block_index, time_us)) {
            fprintf(stderr, "pulseq-cpp-oracle: line %ld of stdin is not 'block_index time_us': %s\n",
                    line_number, line.c_str());
            return 2;
        }
        if (block_index < 0 || block_index >= sequence.GetNumberOfBlocks()) {
            fprintf(stderr, "pulseq-cpp-oracle: line %ld of stdin: block %ld is not in 0..%d\n",
                    line_number, block_index, sequence.GetNumberOfBlocks() - 1);
            return 2;
        }
        SeqBlock*& block = cache.blocks[static_cast<int>(block_index)];
        if (block == NULL) {
            block = sequence.GetBlock(static_cast<int>(block_index));
            if (!sequence.decodeBlock(block)) {
                fprintf(stderr, "pulseq-cpp-oracle: decodeBlock returned false for block %ld\n",
                        block_index);
                return 1;
            }
        }
        std::vector<double> gradients;
        g_silent = true;
        block->gradientsAt(time_us, gradients);
        g_silent = false;
        printf("%.17g %.17g %.17g\n", gradients[0], gradients[1], gradients[2]);
    }
    fflush(stdout);
    return 0;
}

// ---- The present mode ----

static int run_check(const char* path) {
    ExternalSequence sequence;
    if (!sequence.load(path)) {
        fprintf(stderr, "pulseq-cpp-oracle: ExternalSequence::load returned false\n");
        return 1;
    }
    int failed = 0;
    for (int block = 0; block < sequence.GetNumberOfBlocks(); block++) {
        SeqBlock* seq_block = sequence.GetBlock(block);
        if (!sequence.decodeBlock(seq_block)) {
            fprintf(stderr, "pulseq-cpp-oracle: decodeBlock returned false for block %d\n", block);
            failed++;
        }
        delete seq_block;
    }
    return failed > 0 ? 1 : 0;
}

int main(int argc, char** argv) {
    const std::string mode = argc == 3 ? argv[1] : "";
    if (argc != 2 && mode != "--dump" && mode != "--sample") {
        fprintf(stderr, "usage: %s file.seq | %s --dump file.seq | %s --sample file.seq\n",
                argv[0], argv[0], argv[0]);
        return 2;
    }
    for (int signal_number : {SIGSEGV, SIGABRT, SIGFPE, SIGILL, SIGBUS, SIGTRAP}) {
        signal(signal_number, on_crash);
    }
    ExternalSequence::SetPrintFunction(&print_to_stderr);
    try {
        if (argc == 2) {
            return run_check(argv[1]);
        }
        return mode == "--dump" ? run_dump(argv[2]) : run_sample(argv[2]);
    } catch (const std::exception& error) {
        fprintf(stderr, "pulseq-cpp-oracle: exception: %s\n", error.what());
        return 1;
    }
}
