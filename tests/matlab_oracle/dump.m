function dump(files, outdir)
%DUMP Write what MATLAB Pulseq reads from each .seq file as JSON.
%   dump(files, outdir) reads each file of the cell array of file names with
%   mr.Sequence().read and writes outdir/<stem>.json. A file that MATLAB
%   cannot read gives {"error": message}. The layout is in README.md.
%   pulseq-matlab-oracle (flake.nix) calls this function in one Octave process.

  for i = 1:numel(files)
    f = files{i};
    [~, stem] = fileparts(f);
    t0 = tic;
    try
      out = dump_one(f);
      status = 'ok';
    catch err
      out = struct('error', err.message);
      status = ['error: ' strtok(err.message, sprintf('\n'))];
    end
    fid = fopen(fullfile(outdir, [stem '.json']), 'w');
    if fid < 0
      error('dump: cannot write %s', fullfile(outdir, [stem '.json']));
    end
    fputs(fid, jsonencode(out));
    fclose(fid);
    printf('%-45s %6.2f s  %s\n', stem, toc(t0), status);
  end
end

function out = dump_one(f)
  seq = mr.Sequence();
  seq.read(f);

  out = struct();
  out.version = file_version(f);
  out.toolbox_version = struct('major', seq.version_major, ...
                               'minor', seq.version_minor, ...
                               'revision', seq.version_revision);
  [out.definitions, out.definitions_numeric] = definitions_plain(seq.definitions);
  out.block_durations = arr(seq.blockDurations);

  n = numel(seq.blockDurations);
  blocks = cell(1, n);
  for b = 1:n
    blocks{b} = block_plain(seq.getBlock(b));
  end
  out.blocks = blocks;

  [wave, ~, ~, t_adc] = seq.waveforms_and_times(true);
  out.waveforms = waveforms_plain(wave);
  out.t_adc = arr(t_adc);
end

function v = file_version(f)
  % read() of MATLAB Pulseq checks the three numbers of [VERSION] but keeps them in
  % local variables, so this repeats its readVersion on the three lines.
  v = struct('major', [], 'minor', [], 'revision', []);
  lines = strsplit(fileread(f), "\n", 'CollapseDelimiters', false);
  k = find(strcmp(strtrim(lines), '[VERSION]'), 1);
  if isempty(k)
    return
  end
  for j = (k + 1):numel(lines)
    line = lines{j};
    if isempty(strtrim(line)) || line(1) == '#'
      break
    end
    tok = strsplit(strtrim(line));
    if numel(tok) >= 2 && any(strcmp(tok{1}, {'major', 'minor', 'revision'}))
      v.(tok{1}) = str2double(tok{2});
    end
  end
  % A number that is missing or not a number gives null.
  for name = {'major', 'minor', 'revision'}
    if isempty(v.(name{1})) || isnan(v.(name{1}))
      v.(name{1}) = NaN;
    end
  end
end

function [text, numeric] = definitions_plain(defs)
  % The values of the map are numeric rows when every token is a finite number, and
  % the text after the key otherwise. text holds all of them as text (a number as the
  % shortest text that gives the same double, joined by spaces), numeric the numeric
  % ones as lists of numbers.
  text = struct();
  numeric = struct();
  names = keys(defs);
  for i = 1:numel(names)
    value = defs(names{i});
    if ischar(value)
      text.(names{i}) = value;
    else
      text.(names{i}) = strjoin(arrayfun(@jsonencode, value(:).', 'UniformOutput', false), ' ');
      numeric.(names{i}) = arr(value);
    end
  end
end

function out = block_plain(blk)
  % The keys of the first group are always in the output. The others follow when
  % getBlock gives them.
  out = struct();
  out.blockDuration = blk.blockDuration;
  for name = {'rf', 'gx', 'gy', 'gz', 'adc'}
    out.(name{1}) = event_or_null(blk.(name{1}));
  end
  for name = {'trig', 'label'}
    out.(name{1}) = {};
    if isfield(blk, name{1})
      list = cell(1, numel(blk.(name{1})));
      for i = 1:numel(list)
        list{i} = event_plain(blk.(name{1})(i));
      end
      out.(name{1}) = list;
    end
  end
  for name = {'rotation', 'softDelay', 'rfShim'}
    out.(name{1}) = NaN;
    if isfield(blk, name{1})
      out.(name{1}) = event_or_null(blk.(name{1}));
    end
  end
  known = {'blockDuration', 'rf', 'gx', 'gy', 'gz', 'adc', 'trig', 'label', ...
           'rotation', 'softDelay', 'rfShim'};
  for name = fieldnames(blk).'
    if ~any(strcmp(name{1}, known))
      out.(name{1}) = value_plain(name{1}, blk.(name{1}));
    end
  end
end

function out = event_or_null(e)
  if isempty(e)
    out = NaN;
  else
    out = event_plain(e);
  end
end

function out = event_plain(e)
  out = struct();
  for name = fieldnames(e).'
    key = name{1};
    value = e.(key);
    if (isnumeric(value) || islogical(value)) && ...
       (~isreal(value) || any(strcmp(key, {'signal', 'shimVector'})))
      % jsonencode drops the imaginary part of a complex array.
      out.([key '_abs']) = arr(abs(value));
      out.([key '_angle']) = arr(angle(value));
    else
      out.(key) = value_plain(key, value);
    end
  end
end

function out = value_plain(key, value)
  % The fields of the events that are arrays. The other numbers are scalars.
  array_fields = {'t', 'tt', 'waveform', 'phaseModulation', 'rotQuaternion'};
  if ischar(value)
    out = value;
  elseif islogical(value) && isscalar(value)
    out = value;
  elseif isnumeric(value) || islogical(value)
    if any(strcmp(key, array_fields))
      out = arr(value);
    elseif isempty(value)
      out = NaN;
    elseif isscalar(value)
      out = double(value);
    else
      out = arr(value);
    end
  elseif isstruct(value) && isscalar(value)
    out = event_plain(value);
  else
    error('dump: field %s has the class %s, which dump.m does not write', key, class(value));
  end
end

function out = waveforms_plain(wave)
  % wave is the cell of waveforms_and_times(true): a 2-row matrix (time, value) for
  % each of gx, gy, gz, then the RF with complex values.
  names = {'gx', 'gy', 'gz', 'rf'};
  out = struct();
  for j = 1:numel(names)
    out.(names{j}) = NaN;
    if j > numel(wave) || size(wave{j}, 2) == 0
      continue
    end
    w = wave{j};
    entry = struct('t', arr(w(1, :)));
    if strcmp(names{j}, 'rf')
      entry.v_abs = arr(abs(w(2, :)));
      entry.v_angle = arr(angle(w(2, :)));
    else
      entry.v = arr(w(2, :));
    end
    out.(names{j}) = entry;
  end
end

function out = arr(x)
  % A flat list for jsonencode. A list of one number stays a list: jsonencode writes
  % a number for a 1-by-1 array and a list for a 1-by-1 cell.
  x = double(x(:).');
  if isempty(x)
    out = {};
  elseif isscalar(x)
    out = {x};
  else
    out = x;
  end
end
