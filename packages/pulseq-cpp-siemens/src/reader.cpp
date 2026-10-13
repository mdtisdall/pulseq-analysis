// A nanobind extension around ExternalSequence of pulseq/pulseq (MIT; LICENSE.pulseq), the reader
// of the Pulseq interpreter on Siemens scanners. It gives what the driver of the C++ oracle
// (tests/cpp_oracle/driver.cpp of pulseq-analysis) writes in its modes --dump and --sample, in
// the process.
//
// The reader keeps state that all its objects share (SeqBlock::s_blockDurationRaster, the print
// function) and it reads numbers with sscanf, which depends on the C locale. Each call into the
// reader therefore holds one mutex, runs with the "C" locale in its thread, and sets
// s_blockDurationRaster to the value of its own sequence. The GIL is released while the mutex is
// held, and no Python object is touched while it is held.
//
// The extension never decides whether a file is safe to decode. pulseq_cpp_siemens calls
// read_version() and refuses a version outside 1.4.0-1.5.x, then calls load(), reads libraries(),
// rejects each case of undefined behaviour, and only then calls mark_checked() and decode_block().
// decode_block() refuses to run before mark_checked().
//
// "cpp:N" is a line of src/ExternalSequence.cpp of pulseq/pulseq at the pinned commit.

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include <algorithm>
#include <clocale>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include <locale.h>
#if defined(__APPLE__)
#include <xlocale.h>
#endif

#include "ExternalSequence.h"

// The reader's helper that turns a vector by a quaternion (cpp:2666-2684): q[0] is the scalar
// part, and c = +1 is the active rotation of the vector, c = -1 that of the conjugate. It is a
// function of ExternalSequence.cpp with external linkage that the header does not declare; the
// reader calls it only on its position offsets (cpp:2773, 3024). gradients_at calls it with
// c = +1 to rotate a block's gradients by the block's rotation, so that the arithmetic of the
// rotation is the reader's own.
void rotate_vec3_by_quat(double* out, const double* q, const double* v, double c);

namespace nb = nanobind;
using namespace nb::literals;

namespace {

// ---- Access to private members of ExternalSequence, without a change to its source. ----
// An explicit instantiation may name a private member (C++11 [temp.explicit]/12), so this
// template hands out a pointer to it. The checks of undefined behaviour read the libraries that
// load() built, so they see the file exactly as the reader read it, and the version gate runs the
// reader's own functions.
template <typename Tag, typename Tag::type Member>
struct Steal {
    friend typename Tag::type get(Tag) { return Member; }
};

#define PRIVATE_MEMBER(NAME, TYPE)                                \
    struct NAME##_tag {                                           \
        typedef TYPE ExternalSequence::*type;                     \
        friend type get(NAME##_tag);                              \
    };                                                            \
    template struct Steal<NAME##_tag, &ExternalSequence::NAME>;

#define PRIVATE_STATIC(NAME, TYPE)                                \
    struct NAME##_tag {                                           \
        typedef TYPE* type;                                       \
        friend type get(NAME##_tag);                              \
    };                                                            \
    template struct Steal<NAME##_tag, &ExternalSequence::NAME>;

typedef void IndexFunction(std::istream&);
typedef void SkipFunction(std::istream&, char*);
PRIVATE_MEMBER(buildFileIndex, IndexFunction)
PRIVATE_MEMBER(skipComments, SkipFunction)
typedef std::map<std::string, int> FileIndexMap;
PRIVATE_MEMBER(m_fileIndex, FileIndexMap)
PRIVATE_STATIC(MAX_LINE_SIZE, const int)
typedef int GetlineFunction(std::istream&, char*, int, bool);
PRIVATE_STATIC(getline, GetlineFunction)

typedef std::map<int, CompressedShape> ShapeMap;
typedef std::map<int, RFEvent> RfMap;
typedef std::map<int, GradEvent> GradMap;
typedef std::map<int, ADCEvent> AdcMap;
typedef std::vector<EventIDs> BlockList;
typedef std::vector<long> DurationList;
typedef std::map<int, ExtensionListEntry> ExtensionMap;
typedef std::map<int, std::pair<std::string, int> > ExtensionNameMap;
typedef std::map<int, TriggerEvent> TriggerMap;
typedef std::map<int, RotationEvent> RotationMap;
typedef std::map<int, LabelEvent> LabelMap_;
typedef std::map<int, SoftDelayEvent> SoftDelayMap;
typedef std::map<int, RfShimmingEvent> RfShimMap;
typedef std::map<std::string, std::string> DefinitionTextMap;
typedef std::map<std::string, std::vector<double> > DefinitionValueMap;
PRIVATE_MEMBER(m_shapeLibrary, ShapeMap)
PRIVATE_MEMBER(m_rfLibrary, RfMap)
PRIVATE_MEMBER(m_gradLibrary, GradMap)
PRIVATE_MEMBER(m_adcLibrary, AdcMap)
PRIVATE_MEMBER(m_blocks, BlockList)
PRIVATE_MEMBER(m_blockDurations_ru, DurationList)
PRIVATE_MEMBER(m_extensionLibrary, ExtensionMap)
PRIVATE_MEMBER(m_extensionNameIDs, ExtensionNameMap)
PRIVATE_MEMBER(m_triggerLibrary, TriggerMap)
PRIVATE_MEMBER(m_rotationLibrary, RotationMap)
PRIVATE_MEMBER(m_labelsetLibrary, LabelMap_)
PRIVATE_MEMBER(m_labelincLibrary, LabelMap_)
PRIVATE_MEMBER(m_softDelayLibrary, SoftDelayMap)
PRIVATE_MEMBER(m_rfShimLibrary, RfShimMap)
PRIVATE_MEMBER(m_definitions_str, DefinitionTextMap)
PRIVATE_MEMBER(m_definitions, DefinitionValueMap)
PRIVATE_MEMBER(m_dAdcRasterTime_us, double)
PRIVATE_MEMBER(m_dGradientRasterTime_us, double)
PRIVATE_MEMBER(m_dBlockDurationRaster_us, double)
PRIVATE_MEMBER(m_dRadiofrequencyRasterTime_us, double)
PRIVATE_MEMBER(version_major, int)
PRIVATE_MEMBER(version_minor, int)
PRIVATE_MEMBER(version_revision, int)
PRIVATE_MEMBER(m_bSignatureDefined, bool)
PRIVATE_MEMBER(m_strSignature, std::string)
PRIVATE_MEMBER(m_strSignatureType, std::string)
PRIVATE_MEMBER(m_strCalculatedMD5Signature, std::string)

// SeqBlock::s_blockDurationRaster is protected: a derived class may set it.
struct BlockRaster : SeqBlock {
    static void set(double value) { s_blockDurationRaster = value; }
    static double value() { return s_blockDurationRaster; }
};

// ---- The one lock of the reader. ----

std::mutex g_reader_mutex;
// While a call holds the mutex, the messages of the reader go here; at other times nowhere.
std::string* g_messages = nullptr;

void capture_message(const std::string& message) {
    if (g_messages != nullptr) {
        *g_messages += message;
        *g_messages += '\n';
    }
}

// The "C" locale in the calling thread only, for sscanf and strtod in the reader.
class CLocaleInThisThread {
  public:
#if defined(_WIN32)
    CLocaleInThisThread() {
        previous_mode_ = _configthreadlocale(_ENABLE_PER_THREAD_LOCALE);
        const char* name = setlocale(LC_ALL, nullptr);
        previous_ = name ? name : "C";
        setlocale(LC_ALL, "C");
    }
    ~CLocaleInThisThread() {
        setlocale(LC_ALL, previous_.c_str());
        _configthreadlocale(previous_mode_);
    }

  private:
    int previous_mode_;
    std::string previous_;
#else
    CLocaleInThisThread() {
        static locale_t c_locale = newlocale(LC_ALL_MASK, "C", (locale_t)0);
        previous_ = uselocale(c_locale);
    }
    ~CLocaleInThisThread() { uselocale(previous_); }

  private:
    locale_t previous_;
#endif
};

// Holds the mutex, the locale and the message buffer for one call. Construct it with the GIL
// released.
class ReaderCall {
  public:
    explicit ReaderCall(std::string& messages, double block_raster_us)
        : lock_(g_reader_mutex) {
        messages.clear();
        g_messages = &messages;
        BlockRaster::set(block_raster_us);
    }
    ~ReaderCall() { g_messages = nullptr; }

  private:
    std::lock_guard<std::mutex> lock_;
    CLocaleInThisThread locale_;
};

// ---- The version gate. ----

// The first lines of ExternalSequence::load(std::istream&) (cpp:850-910) on a fresh reader: the
// index of the sections, then the [VERSION] section, with the reader's own buildFileIndex and
// skipComments and the same sscanf calls. It gives what load would hold in version_major,
// version_minor and version_revision, before load reads anything else. found is false when
// load would return false at this point: no [VERSION] section, a field that does not decode, or
// an unknown field. load itself does not stop for a version below 1.4.0: it converts the blocks
// of a 1.2 or 1.3 file with GetBlock (cpp:1656-1663), before any check could run.
struct VersionRead {
    bool found;
    int major, minor, revision;
};

VersionRead read_version_as_load(ExternalSequence& sequence, std::istream& stream) {
    VersionRead out = {false, 0, 0, 0};
    if (!stream.good()) return out;
    (sequence.*get(buildFileIndex_tag()))(stream);
    std::map<std::string, int>& index = sequence.*get(m_fileIndex_tag());
    if (index.find("[VERSION]") == index.end()) return out;
    std::vector<char> line(static_cast<size_t>(*get(MAX_LINE_SIZE_tag())), '\0');
    char* buffer = line.data();
    stream.seekg(index["[VERSION]"], std::ios::beg);
    (sequence.*get(skipComments_tag()))(stream, buffer);
    while (stream.good() && buffer[0] != '[') {
        if (0 == strncmp(buffer, "major", 5)) {
            if (1 != sscanf(buffer + 5, "%d", &out.major)) return out;
        } else if (0 == strncmp(buffer, "minor", 5)) {
            if (1 != sscanf(buffer + 5, "%d", &out.minor)) return out;
        } else if (0 == strncmp(buffer, "revision", 8)) {
            if (1 != sscanf(buffer + 8, "%d", &out.revision)) return out;
        } else {
            return out;
        }
        (sequence.*get(skipComments_tag()))(stream, buffer);
    }
    out.found = true;
    return out;
}

// ---- The rows of [GRADIENTS] and [TRAP], as load reads them. ----

// load reads each row of [GRADIENTS] into a GradEvent that it does not initialize (cpp:1069)
// and sets no ramp or flat time; a row of shape 0 is then played as a trapezoid with whatever
// those fields held. In the libraries such an event looks like a row of [TRAP], so the check
// (ub.gradient-shape-0) needs the rows themselves. This reads the two sections again with the
// reader's own getline and the sscanf formats of load (cpp:1060-1124), from the positions of the
// index that load built, in the text that it read. A row that sscanf does not read in full is
// left out: load would have rejected the file.
struct GradientRow {
    int id;
    float amplitude;
    int wave_shape, time_shape, delay;
};

struct TrapRow {
    int id;
    float amplitude;
    int delay;
};

void read_gradient_rows(ExternalSequence& sequence, const std::string& text,
                        std::vector<GradientRow>& gradients, std::vector<TrapRow>& traps) {
    std::map<std::string, int>& index = sequence.*get(m_fileIndex_tag());
    const int size = *get(MAX_LINE_SIZE_tag());
    GetlineFunction* read_line = get(getline_tag());
    std::vector<char> line(static_cast<size_t>(size), '\0');
    char* buffer = line.data();
    const int version = sequence.GetVersion();
    if (index.find("[GRADIENTS]") != index.end()) {
        std::istringstream stream(text, std::ios::in | std::ios::binary);
        stream.seekg(index["[GRADIENTS]"], std::ios::beg);
        while (read_line(stream, buffer, size, false)) {
            if (buffer[0] == '[' || strlen(buffer) == 0) break;
            GradientRow row = {0, 0.0f, 0, 0, 0};
            float first, last;
            if (version >= 1005000L) {
                if (7 != sscanf(buffer, "%d%f%f%f%d%d%d", &row.id, &row.amplitude, &first, &last,
                                &row.wave_shape, &row.time_shape, &row.delay)) {
                    continue;
                }
            } else if (5 != sscanf(buffer, "%d%f%d%d%d", &row.id, &row.amplitude, &row.wave_shape,
                                   &row.time_shape, &row.delay)) {
                continue;
            }
            gradients.push_back(row);
        }
    }
    if (index.find("[TRAP]") != index.end()) {
        std::istringstream stream(text, std::ios::in | std::ios::binary);
        stream.seekg(index["[TRAP]"], std::ios::beg);
        while (read_line(stream, buffer, size, false)) {
            if (buffer[0] == '[' || strlen(buffer) == 0) break;
            TrapRow row = {0, 0.0f, 0};
            long ramp_up, flat, ramp_down;
            if (6 == sscanf(buffer, "%d%f%ld%ld%ld%d", &row.id, &row.amplitude, &ramp_up, &flat,
                            &ramp_down, &row.delay)) {
                traps.push_back(row);
            }
        }
    }
}

// ---- The values of a decoded block, as C++ data (built under the mutex, converted after). ----

struct RfValues {
    RFEvent event;
    float dwell_us;
    std::vector<float> magnitude, phase;
};

struct GradValues {
    int kind;  // 0 none, 1 trap, 2 ext_trap, 3 arbitrary
    GradEvent event;
    std::vector<long> times_us;
    std::vector<float> shape;
    bool oversampled;
};

struct LabelValue {
    std::string label;
    long value;
    bool flag;
};

struct BlockValues {
    int index;
    long duration_ru;
    bool has_rf, has_adc, has_trigger, has_soft_delay, has_rotation, has_rf_shim;
    RfValues rf;
    GradValues grad[NUM_GRADS];
    ADCEvent adc;
    TriggerEvent trigger;
    SoftDelayEvent soft_delay;
    std::vector<LabelValue> labelset, labelinc;
    double rotation[4];
    RfShimmingEvent rf_shim;
};

LabelValue label_value(ExternalSequence& sequence, const LabelEvent& event) {
    if (event.flagVal.first != FLAG_UNKNOWN) {
        return {sequence.getFlagIdAsString(event.flagVal.first), event.flagVal.second ? 1L : 0L,
                true};
    }
    return {sequence.getCounterIdAsString(event.numVal.first),
            static_cast<long>(event.numVal.second), false};
}

std::vector<LabelValue> label_values(ExternalSequence& sequence,
                                     std::vector<LabelEvent>& events) {
    std::vector<LabelValue> out;
    for (size_t i = 0; i < events.size(); i++) out.push_back(label_value(sequence, events[i]));
    return out;
}

// The same accessors as dump_block of the driver.
BlockValues block_values(ExternalSequence& sequence, SeqBlock* block) {
    BlockValues v;
    v.index = block->GetIndex();
    v.duration_ru = block->GetStoredDuration_ru();
    v.has_rf = block->isRF();
    if (v.has_rf) {
        v.rf.event = block->GetRFEvent();
        v.rf.dwell_us = block->GetRFDwellTime();
        const int length = block->GetRFLength();
        if (length > 0) {
            v.rf.magnitude.assign(block->GetRFAmplitudePtr(), block->GetRFAmplitudePtr() + length);
            v.rf.phase.assign(block->GetRFPhasePtr(), block->GetRFPhasePtr() + length);
        }
    }
    for (int c = 0; c < NUM_GRADS; c++) {
        GradValues& g = v.grad[c];
        g.kind = block->isTrapGradient(c)        ? 1
                 : block->isExtTrapGradient(c)   ? 2
                 : block->isArbitraryGradient(c) ? 3
                                                 : 0;
        g.oversampled = false;
        if (g.kind == 0) continue;
        g.event = block->GetGradEvent(c);
        if (g.kind == 2) {
            g.times_us = block->GetExtTrapGradTimes(c);
            g.shape = block->GetExtTrapGradShape(c);
        } else if (g.kind == 3) {
            const int length = block->GetArbGradNumSamples(c);
            if (length > 0) {
                g.shape.assign(block->GetArbGradShapePtr(c), block->GetArbGradShapePtr(c) + length);
            }
            g.oversampled = block->isArbGradWithOversampling(c);
        }
    }
    v.has_adc = block->isADC();
    if (v.has_adc) v.adc = block->GetADCEvent();
    v.has_trigger = block->isTrigger();
    if (v.has_trigger) v.trigger = block->GetTriggerEvent();
    v.has_soft_delay = block->isSoftDelay();
    if (v.has_soft_delay) v.soft_delay = block->GetSoftDelayEvent();
    v.labelset = label_values(sequence, block->GetLabelSetEvents());
    v.labelinc = label_values(sequence, block->GetLabelIncEvents());
    v.has_rotation = block->isRotation();
    if (v.has_rotation) {
        const double* q = block->GetRotationEvent().rotQuaternion;
        for (int i = 0; i < 4; i++) v.rotation[i] = q[i];
    }
    v.has_rf_shim = block->hasRfShim();
    if (v.has_rf_shim) v.rf_shim = block->GetRfShim();
    return v;
}

// ---- Conversion to Python (with the GIL, after the mutex is released). ----

// A float of the reader as a Python float: exact (float to double is exact).
nb::float_ f32(float value) { return nb::float_(static_cast<double>(value)); }

nb::bytes as_bytes(const std::string& text) { return nb::bytes(text.data(), text.size()); }

template <typename T>
nb::object array1d(const std::vector<T>& values) {
    T* data = new T[values.size() > 0 ? values.size() : 1];
    std::copy(values.begin(), values.end(), data);
    nb::capsule owner(data, [](void* p) noexcept { delete[] static_cast<T*>(p); });
    return nb::cast(nb::ndarray<nb::numpy, T, nb::ndim<1>>(data, {values.size()}, owner));
}

nb::dict rf_event(const RFEvent& rf) {
    nb::dict d;
    d["amplitude"] = f32(rf.amplitude);
    d["mag_shape"] = rf.magShape;
    d["phase_shape"] = rf.phaseShape;
    d["time_shape"] = rf.timeShape;
    d["shape_dur_us"] = f32(rf.shape_dur);
    d["center_us"] = f32(rf.center);
    d["delay_us"] = rf.delay;
    d["freq_ppm"] = f32(rf.freqPPM);
    d["phase_ppm"] = f32(rf.phasePPM);
    d["freq_offset"] = f32(rf.freqOffset);
    d["phase_offset"] = f32(rf.phaseOffset);
    d["use"] = nb::bytes(&rf.use, 1);
    return d;
}

nb::dict adc_event(const ADCEvent& a) {
    nb::dict d;
    d["num_samples"] = a.numSamples;
    d["dwell_ns"] = a.dwellTime;
    d["delay_us"] = a.delay;
    d["freq_ppm"] = f32(a.freqPPM);
    d["phase_ppm"] = f32(a.phasePPM);
    d["freq_offset"] = f32(a.freqOffset);
    d["phase_offset"] = f32(a.phaseOffset);
    d["phase_shape"] = a.phaseModulationShapeID;
    return d;
}

nb::dict trigger_event(const TriggerEvent& t) {
    nb::dict d;
    d["type"] = t.triggerType;
    d["channel"] = t.triggerChannel;
    d["delay_us"] = t.delay;
    d["duration_us"] = t.duration;
    return d;
}

nb::dict soft_delay_event(const SoftDelayEvent& s) {
    nb::dict d;
    d["num_id"] = s.numID;
    d["offset_us"] = s.offset;
    d["factor"] = f32(s.factor);
    // The reader keeps the bytes of the file; up to the first zero, at most 31.
    d["hint"] = nb::bytes(s.hint, strnlen(s.hint, SOFT_DELAY_HINT_LENGTH));
    return d;
}

nb::dict rf_shim_event(const RfShimmingEvent& s) {
    nb::dict d;
    d["id"] = s.id;
    d["nchan"] = s.nchan;
    d["amplitudes"] = array1d(s.amplitudes);
    d["phases"] = array1d(s.phases);
    return d;
}

nb::dict label_dict(const LabelValue& label) {
    nb::dict d;
    d["label"] = label.label;
    d["value"] = label.value;
    return d;
}

nb::object to_python(const BlockValues& v) {
    nb::dict block;
    block["index"] = v.index;
    block["duration_ru"] = v.duration_ru;
    if (v.has_rf) {
        nb::dict d = rf_event(v.rf.event);
        d["dwell_us"] = f32(v.rf.dwell_us);
        d["magnitude"] = array1d(v.rf.magnitude);
        d["phase"] = array1d(v.rf.phase);
        block["rf"] = d;
    } else {
        block["rf"] = nb::none();
    }
    nb::list grads;
    for (int c = 0; c < NUM_GRADS; c++) {
        const GradValues& g = v.grad[c];
        if (g.kind == 0) {
            grads.append(nb::none());
            continue;
        }
        nb::dict d;
        d["kind"] = g.kind == 1 ? "trap" : g.kind == 2 ? "ext_trap" : "arbitrary";
        d["amplitude"] = f32(g.event.amplitude);
        d["delay_us"] = g.event.delay;
        if (g.kind == 1) {
            d["ramp_up_us"] = g.event.rampUpTime;
            d["flat_us"] = g.event.flatTime;
            d["ramp_down_us"] = g.event.rampDownTime;
        } else if (g.kind == 2) {
            std::vector<int64_t> times(g.times_us.begin(), g.times_us.end());
            d["times_us"] = array1d(times);
            d["shape"] = array1d(g.shape);
        } else {
            d["wave_shape"] = g.event.waveShape;
            d["time_shape"] = g.event.timeShape;
            d["first"] = f32(g.event.first);
            d["last"] = f32(g.event.last);
            d["oversampled"] = g.oversampled;
            d["samples"] = array1d(g.shape);
        }
        grads.append(d);
    }
    block["grad"] = grads;
    block["adc"] = v.has_adc ? nb::object(adc_event(v.adc)) : nb::none();
    block["trigger"] = v.has_trigger ? nb::object(trigger_event(v.trigger)) : nb::none();
    block["soft_delay"] =
        v.has_soft_delay ? nb::object(soft_delay_event(v.soft_delay)) : nb::none();
    for (int set = 0; set < 2; set++) {
        nb::list labels;
        for (const LabelValue& label : set == 0 ? v.labelset : v.labelinc) {
            labels.append(label_dict(label));
        }
        block[set == 0 ? "labelset" : "labelinc"] = labels;
    }
    if (v.has_rotation) {
        block["rotation"] = nb::make_tuple(v.rotation[0], v.rotation[1], v.rotation[2],
                                           v.rotation[3]);
    } else {
        block["rotation"] = nb::none();
    }
    block["rf_shim"] = v.has_rf_shim ? nb::object(rf_shim_event(v.rf_shim)) : nb::none();
    return block;
}

// ---- The object that Python holds. ----

class Reader {
  public:
    // `oversampling` is the reader's sampling mode of an oversampled arbitrary gradient (time
    // shape -1; cpp:2123-2146): "center" (the default of the reader: the samples at the centres
    // of the rasters), "edge" (SetArbGradCenterSampling(false): those on the edges) or "preserve"
    // (SetArbGradPreserveOversampling: all of them). It is set here, before any block is decoded,
    // and stays: the decoded blocks are kept.
    explicit Reader(const std::string& oversampling = "center")
        : sequence_(new ExternalSequence()), oversampling_(oversampling) {
        if (oversampling == "center") {
            sequence_->SetArbGradCenterSampling(true);
        } else if (oversampling == "edge") {
            sequence_->SetArbGradCenterSampling(false);
        } else if (oversampling == "preserve") {
            sequence_->SetArbGradPreserveOversampling();
        } else {
            throw std::invalid_argument("oversampling is 'center', 'edge' or 'preserve'");
        }
    }

    const std::string& oversampling() const { return oversampling_; }

    // The version gate: (found, major, minor, revision) as load would read them
    // (read_version_as_load), on a reader of its own. Load nothing else.
    std::tuple<bool, int, int, int> read_version(nb::bytes data) {
        std::string text(data.c_str(), data.size());
        VersionRead version;
        {
            nb::gil_scoped_release release;
            std::string dropped;
            ReaderCall call(dropped, BlockRaster::value());
            ExternalSequence fresh;
            std::istringstream stream(text, std::ios::in | std::ios::binary);
            version = read_version_as_load(fresh, stream);
        }
        return std::make_tuple(version.found, version.major, version.minor, version.revision);
    }

    // ExternalSequence::load on the bytes of a file. True when the reader loads it. It runs no
    // GetBlock and no decodeBlock, where the cases of undefined behaviour are, for a file of
    // version 1.4.0 or later (read_version first).
    bool load(nb::bytes data) {
        if (load_called_) throw std::logic_error("a Reader loads one file");
        load_called_ = true;
        text_.assign(data.c_str(), data.size());
        bool ok = false;
        {
            nb::gil_scoped_release release;
            ReaderCall call(messages_, BlockRaster::value());
            std::istringstream stream(text_, std::ios::in | std::ios::binary);
            try {
                ok = sequence_->load(stream);
            } catch (const std::exception& error) {
                messages_ += std::string("exception: ") + error.what() + "\n";
                ok = false;
            }
            block_raster_us_ = (*sequence_).*get(m_dBlockDurationRaster_us_tag());
        }
        loaded_ = ok;
        return ok;
    }

    // What load() put in its libraries, which GetBlock and decodeBlock read. Reading them runs
    // none of the reader's code (but the two lookups of label names, which are map lookups).
    nb::dict libraries() {
        require_loaded();
        ExternalSequence& s = *sequence_;
        nb::dict out;
        out["version"] = s.GetVersion();
        out["version_parts"] = nb::make_tuple(s.*get(version_major_tag()),
                                              s.*get(version_minor_tag()),
                                              s.*get(version_revision_tag()));
        out["adc_raster_us"] = s.*get(m_dAdcRasterTime_us_tag());
        out["gradient_raster_us"] = s.*get(m_dGradientRasterTime_us_tag());
        out["rf_raster_us"] = s.*get(m_dRadiofrequencyRasterTime_us_tag());
        out["block_raster_us"] = s.*get(m_dBlockDurationRaster_us_tag());

        nb::dict definitions;
        for (const auto& item : s.*get(m_definitions_str_tag())) {
            definitions[as_bytes(item.first)] = as_bytes(item.second);
        }
        out["definitions"] = definitions;
        nb::dict definition_values;
        for (const auto& item : s.*get(m_definitions_tag())) {
            definition_values[as_bytes(item.first)] = array1d(item.second);
        }
        out["definition_values"] = definition_values;

        const BlockList& blocks = s.*get(m_blocks_tag());
        const DurationList& durations = s.*get(m_blockDurations_ru_tag());
        std::vector<int64_t> table;
        table.reserve(blocks.size() * 7);
        for (size_t i = 0; i < blocks.size(); i++) {
            // load keeps one duration for each block (cpp:1587); a missing one would be a bug of
            // the reader, read here as -1.
            table.push_back(i < durations.size() ? static_cast<int64_t>(durations[i]) : -1);
            for (int e = 0; e < NUM_EVENTS; e++) table.push_back(blocks[i].id[e]);
        }
        int64_t* data = new int64_t[table.size() > 0 ? table.size() : 1];
        std::copy(table.begin(), table.end(), data);
        nb::capsule owner(data, [](void* p) noexcept { delete[] static_cast<int64_t*>(p); });
        out["blocks"] = nb::cast(
            nb::ndarray<nb::numpy, int64_t, nb::ndim<2>>(data, {blocks.size(), 7}, owner));

        nb::dict shapes;
        for (const auto& item : s.*get(m_shapeLibrary_tag())) {
            shapes[nb::int_(item.first)] =
                nb::make_tuple(item.second.numUncompressedSamples, item.second.isCompressed,
                               array1d(item.second.samples));
        }
        out["shapes"] = shapes;
        nb::dict rf;
        for (const auto& item : s.*get(m_rfLibrary_tag())) rf[nb::int_(item.first)] =
            rf_event(item.second);
        out["rf"] = rf;
        // load leaves some fields of a GradEvent unset (its local `GradEvent event;` is not
        // initialized): first and last of a [TRAP] row (cpp:1121), and the ramp and flat times
        // of a [GRADIENTS] row (cpp:1069). They are None here, as decodeBlock's output has no
        // such field for the kind: wave_shape 0 is a trapezoid (its first and last are None),
        // any other an arbitrary gradient or an extended trapezoid (its times are None). A
        // [GRADIENTS] row with wave_shape 0 is read as a trapezoid with times that load never
        // set; those are given as the reader holds them.
        nb::dict grad;
        for (const auto& item : s.*get(m_gradLibrary_tag())) {
            const GradEvent& g = item.second;
            const bool trap = g.waveShape == 0;
            nb::dict d;
            d["amplitude"] = f32(g.amplitude);
            d["delay_us"] = g.delay;
            d["ramp_up_us"] = trap ? nb::object(nb::int_(g.rampUpTime)) : nb::none();
            d["flat_us"] = trap ? nb::object(nb::int_(g.flatTime)) : nb::none();
            d["ramp_down_us"] = trap ? nb::object(nb::int_(g.rampDownTime)) : nb::none();
            d["wave_shape"] = g.waveShape;
            d["time_shape"] = g.timeShape;
            d["first"] = trap ? nb::object(nb::none()) : nb::object(f32(g.first));
            d["last"] = trap ? nb::object(nb::none()) : nb::object(f32(g.last));
            grad[nb::int_(item.first)] = d;
        }
        out["grad"] = grad;
        nb::dict adc;
        for (const auto& item : s.*get(m_adcLibrary_tag())) adc[nb::int_(item.first)] =
            adc_event(item.second);
        out["adc"] = adc;
        nb::dict extensions;
        for (const auto& item : s.*get(m_extensionLibrary_tag())) {
            extensions[nb::int_(item.first)] =
                nb::make_tuple(item.second.type, item.second.ref, item.second.next);
        }
        out["extension_list"] = extensions;
        nb::dict extension_types;
        for (const auto& item : s.*get(m_extensionNameIDs_tag())) {
            extension_types[nb::int_(item.first)] =
                nb::make_tuple(as_bytes(item.second.first), item.second.second);
        }
        out["extension_types"] = extension_types;
        nb::dict triggers;
        for (const auto& item : s.*get(m_triggerLibrary_tag())) triggers[nb::int_(item.first)] =
            trigger_event(item.second);
        out["triggers"] = triggers;
        nb::dict rotations;
        for (const auto& item : s.*get(m_rotationLibrary_tag())) {
            const double* q = item.second.rotQuaternion;
            rotations[nb::int_(item.first)] = nb::make_tuple(q[0], q[1], q[2], q[3]);
        }
        out["rotations"] = rotations;
        for (int set = 0; set < 2; set++) {
            nb::dict labels;
            const LabelMap_& library =
                set == 0 ? s.*get(m_labelsetLibrary_tag()) : s.*get(m_labelincLibrary_tag());
            for (const auto& item : library) {
                const LabelValue label = label_value(s, item.second);
                nb::dict d = label_dict(label);
                d["flag"] = label.flag;
                labels[nb::int_(item.first)] = d;
            }
            out[set == 0 ? "labelset" : "labelinc"] = labels;
        }
        nb::dict soft_delays;
        for (const auto& item : s.*get(m_softDelayLibrary_tag())) {
            soft_delays[nb::int_(item.first)] = soft_delay_event(item.second);
        }
        out["soft_delays"] = soft_delays;
        nb::dict rf_shims;
        for (const auto& item : s.*get(m_rfShimLibrary_tag())) rf_shims[nb::int_(item.first)] =
            rf_shim_event(item.second);
        out["rf_shims"] = rf_shims;

        nb::dict signature;
        signature["defined"] = s.*get(m_bSignatureDefined_tag());
        signature["type"] = as_bytes(s.*get(m_strSignatureType_tag()));
        signature["value"] = as_bytes(s.*get(m_strSignature_tag()));
        signature["calculated"] = as_bytes(s.*get(m_strCalculatedMD5Signature_tag()));
        signature["ok"] = s.isSignatureCheckSucceeded();
        out["signature"] = signature;
        return out;
    }

    // The rows of [GRADIENTS] (id, amplitude, wave shape, time shape, delay) and of [TRAP] (id,
    // amplitude, delay) of the loaded file, as load reads them (read_gradient_rows).
    nb::tuple gradient_rows() {
        require_loaded();
        std::vector<GradientRow> gradients;
        std::vector<TrapRow> traps;
        {
            nb::gil_scoped_release release;
            std::string dropped;
            ReaderCall call(dropped, block_raster_us_);
            read_gradient_rows(*sequence_, text_, gradients, traps);
        }
        nb::list out_gradients, out_traps;
        for (const GradientRow& r : gradients) {
            out_gradients.append(
                nb::make_tuple(r.id, f32(r.amplitude), r.wave_shape, r.time_shape, r.delay));
        }
        for (const TrapRow& r : traps) {
            out_traps.append(nb::make_tuple(r.id, f32(r.amplitude), r.delay));
        }
        return nb::make_tuple(out_gradients, out_traps);
    }

    void mark_checked() {
        require_loaded();
        checked_ = true;
    }

    int block_count() {
        require_loaded();
        return static_cast<int>((*sequence_.*get(m_blocks_tag())).size());
    }

    // GetBlock and decodeBlock of one block (play order from 0), as the driver's --dump gives
    // it. The decoded block is kept for gradients_at. None when decodeBlock returns false or the
    // reader throws (the messages say which).
    nb::object decode_block(int index) {
        require_checked();
        if (index < 0 || index >= block_count()) {
            throw std::out_of_range("the block index is not a block of the sequence");
        }
        BlockValues values;
        bool ok = false;
        {
            nb::gil_scoped_release release;
            ReaderCall call(messages_, block_raster_us_);
            ok = decode_locked(index);
            if (ok) values = block_values(*sequence_, blocks_[index].get());
        }
        if (!ok) return nb::none();
        return to_python(values);
    }

    // Decodes each block of `indices` that is not decoded yet. The index of the first block that
    // decodeBlock rejects, or -1.
    int ensure_decoded(
        nb::ndarray<const int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu> indices) {
        require_checked();
        const int count = block_count();
        const size_t n = indices.shape(0);
        for (size_t i = 0; i < n; i++) {
            if (indices(i) < 0 || indices(i) >= count) {
                throw std::out_of_range("a block index is not a block of the sequence");
            }
        }
        int failed = -1;
        {
            nb::gil_scoped_release release;
            ReaderCall call(messages_, block_raster_us_);
            for (size_t i = 0; i < n && failed < 0; i++) {
                const int index = static_cast<int>(indices(i));
                if (blocks_.count(index) == 0 && !decode_locked(index)) failed = index;
            }
        }
        return failed;
    }

    // SeqBlock::gradientsAt for each pair of a block index and a time (us from the block start),
    // as an array (n, 3) of Hz/m: the driver's --sample. Each block must be decoded first. Its
    // messages are dropped, as the driver drops them. A NaN time is refused: gradientsAt would
    // convert it to an int (cpp:3666), which is undefined behaviour.
    //
    // With `rotated`, the values of each block that has a rotation (SeqBlock::isRotation) are
    // turned by its quaternion with the reader's rotate_vec3_by_quat (c = +1): the gradients
    // that the scanner plays when it applies the rotation. The reader itself never does this
    // (gradientsAt never reads the rotation); it is the package's simulation.
    nb::ndarray<nb::numpy, double, nb::shape<-1, 3>> gradients_at(
        nb::ndarray<const int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu> block_index,
        nb::ndarray<const double, nb::ndim<1>, nb::c_contig, nb::device::cpu> time_us,
        bool rotated) {
        require_checked();
        if (block_index.shape(0) != time_us.shape(0)) {
            throw std::invalid_argument("block_index and time_us differ in length");
        }
        const size_t n = time_us.shape(0);
        for (size_t i = 0; i < n; i++) {
            if (std::isnan(time_us(i))) throw std::invalid_argument("a time is NaN");
        }
        double* out = new double[3 * (n > 0 ? n : 1)];
        nb::capsule owner(out, [](void* p) noexcept { delete[] static_cast<double*>(p); });
        bool decoded = true;
        {
            nb::gil_scoped_release release;
            std::string dropped;
            ReaderCall call(dropped, block_raster_us_);
            for (size_t i = 0; i < n && decoded; i++) {
                decoded = blocks_.count(static_cast<int>(block_index(i))) > 0 &&
                          block_index(i) == static_cast<int>(block_index(i));
            }
            for (size_t i = 0; i < n && decoded; i++) {
                // A vector of its own for each time, as the driver has for each line:
                // gradientsAt returns early where an oversampled gradient of 1 or 2 samples has
                // none in the "edge" mode (cpp:3673-3677) and leaves the channels after it as
                // they were.
                std::vector<double> g;
                SeqBlock* block = blocks_[static_cast<int>(block_index(i))].get();
                block->gradientsAt(time_us(i), g);
                if (rotated && block->isRotation()) {
                    rotate_vec3_by_quat(out + 3 * i, block->GetRotationEvent().rotQuaternion,
                                        g.data(), 1.0);
                } else {
                    out[3 * i] = g[0];
                    out[3 * i + 1] = g[1];
                    out[3 * i + 2] = g[2];
                }
            }
        }
        if (!decoded) throw std::out_of_range("a block index is not a decoded block");
        return nb::ndarray<nb::numpy, double, nb::shape<-1, 3>>(out, {n, 3}, owner);
    }

    // The rotation of each block, as GetBlock attaches it (cpp:1871-1879: the first defined
    // rotation of the block's extension list): the play index of each block for which
    // SeqBlock::isRotation is true, and its quaternion, which load divided by its norm. GetBlock
    // runs only for a block with an extension list; no block is decoded or kept, and the
    // reader's messages (its warnings for a second rotation) are dropped.
    nb::tuple block_rotations() {
        require_checked();
        std::vector<int64_t> indices;
        std::vector<double> quaternions;
        {
            nb::gil_scoped_release release;
            std::string dropped;
            ReaderCall call(dropped, block_raster_us_);
            const BlockList& list = *sequence_.*get(m_blocks_tag());
            for (size_t index = 0; index < list.size(); index++) {
                if (list[index].id[EXT] <= 0) continue;
                std::unique_ptr<SeqBlock> block(sequence_->GetBlock(static_cast<int>(index)));
                if (!block->isRotation()) continue;
                const double* q = block->GetRotationEvent().rotQuaternion;
                indices.push_back(static_cast<int64_t>(index));
                quaternions.insert(quaternions.end(), q, q + 4);
            }
        }
        const size_t n = indices.size();
        int64_t* out_indices = new int64_t[n > 0 ? n : 1];
        double* out_quaternions = new double[4 * (n > 0 ? n : 1)];
        std::copy(indices.begin(), indices.end(), out_indices);
        std::copy(quaternions.begin(), quaternions.end(), out_quaternions);
        nb::capsule owns_indices(
            out_indices, [](void* p) noexcept { delete[] static_cast<int64_t*>(p); });
        nb::capsule owns_quaternions(
            out_quaternions, [](void* p) noexcept { delete[] static_cast<double*>(p); });
        return nb::make_tuple(
            nb::ndarray<nb::numpy, int64_t, nb::ndim<1>>(out_indices, {n}, owns_indices),
            nb::ndarray<nb::numpy, double, nb::shape<-1, 4>>(out_quaternions, {n, 4},
                                                              owns_quaternions));
    }

    // GetBlock and decodeBlock of every block in play order, as the driver's first mode does:
    // it goes on after a block that decodeBlock rejects (or that throws), and it keeps no
    // block, so that a file of 900 000 blocks needs no more memory than one block. The index of
    // the first block that is rejected, or -1. `messages` then has the messages of that block
    // (also the messages of its decodeBlock), not those of the blocks before or after it.
    int first_rejected_block() {
        require_checked();
        const int count = block_count();
        int first = -1;
        std::string first_messages;
        {
            nb::gil_scoped_release release;
            ReaderCall call(messages_, block_raster_us_);
            for (int index = 0; index < count; index++) {
                messages_.clear();
                bool ok = false;
                try {
                    std::unique_ptr<SeqBlock> block(sequence_->GetBlock(index));
                    ok = sequence_->decodeBlock(block.get());
                } catch (const std::exception& error) {
                    messages_ += std::string("exception: ") + error.what() + "\n";
                    ok = false;
                }
                if (ok) continue;
                messages_ += "decodeBlock returned false for block " + std::to_string(index) + "\n";
                if (first < 0) {
                    first = index;
                    first_messages = messages_;
                }
            }
            messages_ = first_messages;
        }
        return first;
    }

    const std::string& messages() const { return messages_; }

  private:
    // GetBlock and decodeBlock of one block, kept in blocks_ when it decodes. Call it with a
    // ReaderCall alive.
    bool decode_locked(int index) {
        std::unique_ptr<SeqBlock> block(sequence_->GetBlock(index));
        bool ok = false;
        try {
            ok = sequence_->decodeBlock(block.get());
        } catch (const std::exception& error) {
            messages_ += std::string("exception: ") + error.what() + "\n";
            ok = false;
        }
        if (ok) {
            blocks_[index] = std::move(block);
        } else {
            messages_ += "decodeBlock returned false for block " + std::to_string(index) + "\n";
        }
        return ok;
    }

    void require_loaded() const {
        if (!loaded_) throw std::logic_error("no file is loaded");
    }

    void require_checked() const {
        require_loaded();
        if (!checked_) throw std::logic_error("the file is not checked: call mark_checked()");
    }

    std::unique_ptr<ExternalSequence> sequence_;
    std::string oversampling_;
    std::map<int, std::unique_ptr<SeqBlock> > blocks_;
    std::string messages_;
    std::string text_;  // the bytes that load read
    double block_raster_us_ = 10.0;
    bool load_called_ = false;
    bool loaded_ = false;
    bool checked_ = false;
};

}  // namespace

NB_MODULE(_reader, m) {
    m.doc() = "ExternalSequence of pulseq/pulseq (MIT), in the process";
    ExternalSequence::SetPrintFunction(&capture_message);
    m.attr("PULSEQ_COMMIT") = PULSEQ_COMMIT;
    m.attr("SIZEOF_LONG") = static_cast<int>(sizeof(long));
    m.attr("SIZEOF_INT") = static_cast<int>(sizeof(int));
    nb::class_<Reader>(m, "Reader")
        .def(nb::init<const std::string&>(), "oversampling"_a = "center")
        .def("read_version", &Reader::read_version, "data"_a)
        .def("load", &Reader::load, "data"_a)
        .def("libraries", &Reader::libraries)
        .def("gradient_rows", &Reader::gradient_rows)
        .def("mark_checked", &Reader::mark_checked)
        .def("block_count", &Reader::block_count)
        .def("decode_block", &Reader::decode_block, "index"_a)
        .def("ensure_decoded", &Reader::ensure_decoded, "indices"_a)
        .def("gradients_at", &Reader::gradients_at, "block_index"_a, "time_us"_a,
             "rotated"_a = false)
        .def("block_rotations", &Reader::block_rotations)
        .def("first_rejected_block", &Reader::first_rejected_block)
        .def_prop_ro("oversampling", &Reader::oversampling)
        .def_prop_ro("messages", &Reader::messages);
}
