function dump_safe(mode, args)
%DUMP_SAFE Write what the original SAFE package gives, for the SAFE oracle.
%   dump_safe('filter', {request, outdir}) reads the JSON file request and
%   writes, for each case of its "cases", the rows of safe_gwf_to_pns of the
%   case's waveform (outdir/<id>.f64) and the inputs as read
%   (outdir/<id>.inputs.f64), and, for each case of its "hw_checks", the
%   result of safe_hw_check (outdir/hw_check.json).
%   dump_safe('calcpns', {asc, outdir, file1, file2, ...}) reads each .seq
%   file with mr.Sequence().read, calls calcPNS with the .asc file asc, and
%   writes outdir/<stem>.json and outdir/<stem>.f64.
%   The layouts are in README.md. pulseq-safe-oracle (flake.nix) calls this
%   function in one Octave process.

  switch mode
    case 'filter'
      dump_filter(args{1}, args{2});
    case 'calcpns'
      dump_calcpns(args{1}, args{2}, args(3:end));
    otherwise
      error('dump_safe: unknown mode %s', mode);
  end
end

function dump_filter(request, outdir)
  req = jsondecode(fileread(request));
  folder = fileparts(request);
  fields = {'tau1', 'tau2', 'tau3', 'a1', 'a2', 'a3', 'stim_limit', 'stim_thresh', 'g_scale'};
  cases = as_cell(req.cases);
  for i = 1:numel(cases)
    c = cases{i};
    gwf = read_f64(fullfile(folder, c.gwf), [3, c.rows]).';
    % No padding, and a row of 0 in front: the first row is the slew from 0 to the first
    % sample, and the filters start from 0.
    pns = safe_gwf_to_pns([zeros(1, 3); gwf], nan(c.rows + 1, 1), c.dt, c.hw, 0);
    write_f64(fullfile(outdir, [c.id '.f64']), pns.');
    inputs = c.dt;
    for axis = {'x', 'y', 'z'}
      for j = 1:numel(fields)
        inputs(end + 1) = c.hw.(axis{1}).(fields{j});
      end
    end
    write_f64(fullfile(outdir, [c.id '.inputs.f64']), inputs);
    printf('%-30s %d rows\n', c.id, c.rows);
  end
  checks = as_cell(req.hw_checks);
  out = cell(1, numel(checks));
  for i = 1:numel(checks)
    try
      out{i} = struct('id', checks{i}.id, 'is_ok', safe_hw_check(checks{i}.hw));
    catch err
      out{i} = struct('id', checks{i}.id, 'error', err.message);
    end
  end
  write_text(fullfile(outdir, 'hw_check.json'), jsonencode(out));
  printf('%d hardware checks\n', numel(checks));
end

function dump_calcpns(asc, outdir, files)
  for i = 1:numel(files)
    f = files{i};
    [~, stem] = fileparts(f);
    t0 = tic;
    try
      seq = mr.Sequence();
      seq.read(f);
      [ok, pns_norm, pns_comp, t_axis] = seq.calcPNS(asc, false);
      % A sequence with no gradient has no sample, and its first time is NaN (null).
      t_first = NaN;
      if ~isempty(t_axis)
        t_first = t_axis(1);
      end
      out = struct('ok', logical(ok), 'gamma', seq.sys.gamma, ...
                   'grad_raster', seq.gradRasterTime, 't_axis_first', t_first, ...
                   'num_samples', numel(t_axis));
      % One row for each sample: the three axes, then the total.
      write_f64(fullfile(outdir, [stem '.f64']), [pns_comp; pns_norm]);
      status = 'ok';
    catch err
      out = struct('error', err.message);
      status = ['error: ' strtok(err.message, sprintf('\n'))];
    end
    write_text(fullfile(outdir, [stem '.json']), jsonencode(out));
    printf('%-45s %6.2f s  %s\n', stem, toc(t0), status);
  end
end

function c = as_cell(x)
  % jsondecode gives a struct array for a list of objects with the same keys, and a cell
  % for one whose objects have other keys.
  if iscell(x)
    c = x(:).';
  else
    c = num2cell(x(:).');
  end
end

function x = read_f64(path, shape)
  fid = fopen(path, 'r');
  if fid < 0
    error('dump_safe: cannot read %s', path);
  end
  x = fread(fid, shape, 'double', 0, 'ieee-le');
  fclose(fid);
end

function write_f64(path, x)
  fid = fopen(path, 'w');
  if fid < 0
    error('dump_safe: cannot write %s', path);
  end
  fwrite(fid, x, 'double', 0, 'ieee-le');
  fclose(fid);
end

function write_text(path, text)
  fid = fopen(path, 'w');
  if fid < 0
    error('dump_safe: cannot write %s', path);
  end
  fputs(fid, text);
  fclose(fid);
end
