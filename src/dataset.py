import glob
import copy
import logging
import numpy as num

from collections import defaultdict
from pyrocko import util, pile, model, config, trace, \
    marker as pmarker
from pyrocko.fdsn import enhanced_sacpz, station as fs
from pyrocko.guts import (Object, Tuple, String, Float, List, Bool, dump_all,
                          load_all)

from .meta import Path, HasPaths, expand_template

guts_prefix = 'wafe'
logger = logging.getLogger('wafe.dataset')


g_sx_cache = {}


def cached_load_stationxml(fn):
    if fn not in g_sx_cache:
        g_sx_cache[fn] = fs.load_xml(filename=fn)

    return g_sx_cache[fn]


g_events_cache = {}


def cached_load_events(fn):
    if fn not in g_events_cache:
        g_events_cache[fn] = model.load_events(fn)

    return g_events_cache[fn]


class InvalidObject(Exception):
    pass


class NotFound(Exception):
    def __init__(self, reason, codes=None, time_range=None):
        self.reason = reason
        self.time_range = time_range
        self.codes = codes

    def __str__(self):
        s = self.reason
        if self.codes:
            s += ' (%s)' % '.'.join(self.codes)

        if self.time_range:
            s += ' (%s - %s)' % (
                util.time_to_str(self.time_range[0]),
                util.time_to_str(self.time_range[1]))

        return s


class DatasetError(Exception):
    pass


class StationCorrection(Object):
    codes = Tuple.T(4, String.T())
    delay = Float.T()
    factor = Float.T()


def load_station_corrections(filename):
    scs = load_all(filename=filename)
    for sc in scs:
        assert isinstance(sc, StationCorrection)

    return scs


def dump_station_corrections(station_corrections, filename):
    return dump_all(station_corrections, filename=filename)


class Dataset(object):

    def __init__(self, event_name=None):
        self.events = []
        self._pile = pile.Pile()
        self._pile_update_args = []
        self.stations = {}
        self.responses = defaultdict(list)
        self.responses_stationxml = []
        self.clippings = {}
        self.blacklist = set()
        self.whitelist_nslc = None
        self.whitelist_nsl = None
        self.station_corrections = {}
        self.station_factors = {}
        self.pick_markers = []
        self.apply_correction_delays = True
        self.apply_correction_factors = True
        self.extend_incomplete = False
        self.clip_handling = 'by_nsl'
        self._picks = None
        self._cache = {}
        self._event_name = event_name

    def empty_cache(self):
        self._cache = {}

    def add_stations(
            self,
            stations=None,
            pyrocko_stations_filename=None,
            stationxml_filenames=None):

        if stations is not None:
            for station in stations:
                self.stations[station.nsl()] = station

        if pyrocko_stations_filename is not None:
            logger.debug(
                'Loading stations from file %s' %
                pyrocko_stations_filename)

            for station in model.load_stations(pyrocko_stations_filename):
                self.stations[station.nsl()] = station

        if stationxml_filenames is not None and len(stationxml_filenames) > 0:

            for stationxml_filename in stationxml_filenames:
                logger.debug(
                    'Loading stations from StationXML file %s' %
                    stationxml_filename)

                sx = cached_load_stationxml(stationxml_filename)
                for station in sx.get_pyrocko_stations():
                    self.stations[station.nsl()] = station

    def add_events(self, events=None, filename=None):
        if events is not None:
            self.events.extend(events)

        if filename is not None:
            logger.debug('Loading events from file %s' % filename)
            self.events.extend(cached_load_events(filename))

    def add_waveforms(self, paths, regex=None, fileformat='detect',
                      show_progress=False):

        self._pile_update_args.append(
            [paths, regex, fileformat, show_progress])

    def _update_pile(self):
        while self._pile_update_args:
            paths, regex, fileformat, show_progress = \
                self._pile_update_args.pop(0)

            logger.debug('Loading waveform data from %s' % paths)

            cachedirname = config.config().cache_dir
            fns = util.select_files(paths, regex=regex,
                                    show_progress=show_progress)
            cache = pile.get_cache(cachedirname)
            self._pile.load_files(sorted(fns), cache=cache,
                                 fileformat=fileformat,
                                 show_progress=show_progress)

    def get_pile(self):
        self._update_pile()
        return self._pile

    def add_responses(self, sacpz_dirname=None, stationxml_filenames=None):
        if sacpz_dirname:
            logger.debug('Loading SAC PZ responses from %s' % sacpz_dirname)
            for x in enhanced_sacpz.iload_dirname(sacpz_dirname):
                self.responses[x.codes].append(x)

        if stationxml_filenames:
            for stationxml_filename in stationxml_filenames:
                logger.debug(
                    'Loading StationXML responses from %s' %
                    stationxml_filename)

                self.responses_stationxml.append(
                    cached_load_stationxml(stationxml_filename))

    def add_clippings(self, markers_filename):
        markers = pmarker.load_markers(markers_filename)
        clippings = {}
        for marker in markers:
            nslc = marker.one_nslc()
            nsl = nslc[:3]
            if nsl not in clippings:
                clippings[nsl] = []

            if nslc not in clippings:
                clippings[nslc] = []

            clippings[nsl].append(marker.tmin)
            clippings[nslc].append(marker.tmin)

        for k, times in clippings.items():
            atimes = num.array(times, dtype=num.float)
            if k not in self.clippings:
                self.clippings[k] = atimes
            else:
                self.clippings[k] = num.concatenate(self.clippings, atimes)

    def add_blacklist(self, blacklist=[], filenames=None):
        logger.debug('Loading blacklisted stations')
        if filenames:
            blacklist = list(blacklist)
            for filename in filenames:
                with open(filename, 'r') as f:
                    blacklist.extend(s.strip() for s in f.read().splitlines())

        for x in blacklist:
            if isinstance(x, str):
                x = tuple(x.split('.'))
            self.blacklist.add(x)

    def add_whitelist(self, whitelist=[], filenames=None):
        logger.debug('Loading whitelisted stations')
        if filenames:
            whitelist = list(whitelist)
            for filename in filenames:
                with open(filename, 'r') as f:
                    whitelist.extend(s.strip() for s in f.read().splitlines())

        if self.whitelist_nslc is None:
            self.whitelist_nslc = set()
            self.whitelist_nsl = set()
            self.whitelist_nsl_xx = set()

        for x in whitelist:
            if isinstance(x, str):
                x = tuple(x.split('.'))
            assert len(x) in (3, 4)
            if len(x) == 4:
                self.whitelist_nslc.add(x)
                self.whitelist_nsl_xx.add(x[:3])
            if len(x) == 3:
                self.whitelist_nsl.add(x)

    def add_station_corrections(self, filename):
        self.station_corrections.update(
            (sc.codes, sc) for sc in load_station_corrections(filename))

    def add_picks(self, filename):
        self.pick_markers.extend(
            pmarker.load_markers(filename))

        self._picks = None

    def is_blacklisted(self, obj):
        try:
            nslc = self.get_nslc(obj)
            if nslc in self.blacklist:
                return True

        except InvalidObject:
            pass

        nsl = self.get_nsl(obj)
        return (
            nsl in self.blacklist or
            nsl[1:2] in self.blacklist or
            nsl[:2] in self.blacklist)

    def is_whitelisted(self, obj):
        if self.whitelist_nslc is None:
            return True

        nsl = self.get_nsl(obj)
        try:
            nslc = self.get_nslc(obj)
            if nslc in self.whitelist_nslc:
                return True

            return nsl in self.whitelist_nsl

        except InvalidObject:
            return nsl in self.whitelist_nsl_xx or nsl in self.whitelist_nsl

    def has_clipping(self, nsl_or_nslc, tmin, tmax):
        if nsl_or_nslc not in self.clippings:
            return False

        atimes = self.clippings[nsl_or_nslc]
        return num.any(num.logical_and(tmin < atimes, atimes <= tmax))

    def get_nsl(self, obj):
        if isinstance(obj, trace.Trace):
            net, sta, loc, _ = obj.nslc_id
        elif isinstance(obj, model.Station):
            net, sta, loc = obj.nsl()
        elif isinstance(obj, tuple) and len(obj) in (3, 4):
            net, sta, loc = obj[:3]
        else:
            raise InvalidObject(
                'cannot get nsl code from given object of type %s' % type(obj))

        return net, sta, loc

    def get_nslc(self, obj):
        if isinstance(obj, trace.Trace):
            return obj.nslc_id
        elif isinstance(obj, tuple) and len(obj) == 4:
            return obj
        else:
            raise InvalidObject(
                'cannot get nslc code from given object %s' % type(obj))

    def get_tmin_tmax(self, obj):
        if isinstance(obj, trace.Trace):
            return obj.tmin, obj.tmax
        else:
            raise InvalidObject(
                'cannot get tmin and tmax from given object of type %s' %
                type(obj))

    def get_station(self, obj):
        if self.is_blacklisted(obj):
            raise NotFound('station is blacklisted', self.get_nsl(obj))

        if not self.is_whitelisted(obj):
            raise NotFound('station is not on whitelist', self.get_nsl(obj))

        if isinstance(obj, model.Station):
            return obj

        net, sta, loc = self.get_nsl(obj)

        keys = [(net, sta, loc), (net, sta, ''), ('', sta, '')]
        for k in keys:
            if k in self.stations:
                return self.stations[k]

        raise NotFound('no station information', keys)

    def get_stations(self):
        return [self.stations[k] for k in sorted(self.stations)
                if not self.is_blacklisted(self.stations[k])
                and self.is_whitelisted(self.stations[k])]

    def get_response(self, obj, quantity='displacement'):
        if (self.responses is None or len(self.responses) == 0) \
                and (self.responses_stationxml is None
                     or len(self.responses_stationxml) == 0):

            raise NotFound('no response information available')

        quantity_to_unit = {
            'displacement': 'M',
            'velocity': 'M/S',
            'acceleration': 'M/S**2'}

        if self.is_blacklisted(obj):
            raise NotFound('response is blacklisted', self.get_nslc(obj))

        if not self.is_whitelisted(obj):
            raise NotFound('response is not on whitelist', self.get_nslc(obj))

        net, sta, loc, cha = self.get_nslc(obj)
        tmin, tmax = self.get_tmin_tmax(obj)

        keys_x = [
            (net, sta, loc, cha), (net, sta, '', cha), ('', sta, '', cha)]

        keys = []
        for k in keys_x:
            if k not in keys:
                keys.append(k)

        candidates = []
        for k in keys:
            if k in self.responses:
                for x in self.responses[k]:
                    if x.tmin < tmin and (x.tmax is None or tmax < x.tmax):
                        if quantity == 'displacement':
                            candidates.append(x.response)
                        elif quantity == 'velocity':
                            candidates.append(trace.MultiplyResponse([
                                x.response,
                                trace.DifferentiationResponse()]))
                        elif quantity == 'acceleration':
                            candidates.append(trace.MultiplyResponse([
                                x.response,
                                trace.DifferentiationResponse(2)]))
                        else:
                            assert False

        for sx in self.responses_stationxml:
            try:
                candidates.append(
                    sx.get_pyrocko_response(
                        (net, sta, loc, cha),
                        timespan=(tmin, tmax),
                        fake_input_units=quantity_to_unit[quantity]))

            except (fs.NoResponseInformation, fs.MultipleResponseInformation):
                pass

        if len(candidates) == 1:
            return candidates[0]

        elif len(candidates) == 0:
            raise NotFound('no response found', (net, sta, loc, cha))
        else:
            raise NotFound('multiple responses found', (net, sta, loc, cha))

    def get_waveform_raw(
            self, obj,
            tmin,
            tmax,
            tpad=0.,
            toffset_noise_extract=0.,
            want_incomplete=False,
            extend_incomplete=False):

        net, sta, loc, cha = self.get_nslc(obj)

        if self.is_blacklisted((net, sta, loc, cha)):
            raise NotFound(
                'waveform is blacklisted', (net, sta, loc, cha))

        if not self.is_whitelisted((net, sta, loc, cha)):
            raise NotFound(
                'waveform is not on whitelist', (net, sta, loc, cha))

        if self.clip_handling == 'by_nsl':
            if self.has_clipping((net, sta, loc), tmin, tmax):
                raise NotFound(
                    'waveform clipped', (net, sta, loc))

        elif self.clip_handling == 'by_nslc':
            if self.has_clipping((net, sta, loc, cha), tmin, tmax):
                raise NotFound(
                    'waveform clipped', (net, sta, loc, cha))

        p = self.get_pile()
        trs = p.all(
            tmin=tmin+toffset_noise_extract,
            tmax=tmax+toffset_noise_extract,
            tpad=tpad,
            trace_selector=lambda tr: tr.nslc_id == (net, sta, loc, cha),
            want_incomplete=want_incomplete or extend_incomplete)

        if toffset_noise_extract != 0.0:
            for tr in trs:
                tr.shift(-toffset_noise_extract)

        if extend_incomplete and len(trs) == 1:
            trs[0].extend(
                tmin + toffset_noise_extract - tpad,
                tmax + toffset_noise_extract + tpad,
                fillmethod='median')

        if not want_incomplete and len(trs) != 1:
            if len(trs) == 0:
                message = 'waveform missing or incomplete'
            else:
                message = 'waveform has gaps'

            raise NotFound(
                message,
                codes=(net, sta, loc, cha),
                time_range=(
                    tmin + toffset_noise_extract - tpad,
                    tmax + toffset_noise_extract + tpad))

        return trs

    def get_waveform_restituted(
            self,
            obj, quantity='displacement',
            tmin=None, tmax=None, tpad=0.,
            tfade=0., freqlimits=None, deltat=None,
            toffset_noise_extract=0.,
            want_incomplete=False,
            extend_incomplete=False):

        trs_raw = self.get_waveform_raw(
            obj, tmin=tmin, tmax=tmax, tpad=tpad+tfade,
            toffset_noise_extract=toffset_noise_extract,
            want_incomplete=want_incomplete,
            extend_incomplete=extend_incomplete)

        trs_restituted = []
        for tr in trs_raw:
            if deltat is not None:
                tr.downsample_to(deltat, snap=True, allow_upsample_max=5)
                tr.deltat = deltat

            resp = self.get_response(tr, quantity=quantity)
            trs_restituted.append(
                tr.transfer(
                    tfade=tfade, freqlimits=freqlimits,
                    transfer_function=resp, invert=True))

        return trs_restituted, trs_raw

    def _get_projections(
            self, station, backazimuth, source, target, tmin, tmax):

        # fill in missing channel information (happens when station file
        # does not contain any channel information)
        if not station.get_channels():
            station = copy.deepcopy(station)

            nsl = station.nsl()
            p = self.get_pile()
            trs = p.all(
                tmin=tmin, tmax=tmax,
                trace_selector=lambda tr: tr.nslc_id[:3] == nsl,
                load_data=False)

            channels = list(set(tr.channel for tr in trs))
            station.set_channels_by_name(*channels)

        projections = []
        projections.extend(station.guess_projections_to_enu(
            out_channels=('E', 'N', 'Z')))

        if source is not None and target is not None:
            backazimuth = source.azibazi_to(target)[1]

        if backazimuth is not None:
            projections.extend(station.guess_projections_to_rtu(
                out_channels=('R', 'T', 'Z'),
                backazimuth=backazimuth))

        if not projections:
            raise NotFound(
                'cannot determine projection of data components',
                station.nsl())

        return projections

    def get_waveform(
            self,
            obj, quantity='displacement',
            tmin=None, tmax=None, tpad=0.,
            tfade=0., freqlimits=None, deltat=None, cache=None,
            backazimuth=None,
            source=None,
            target=None,
            debug=False):

        assert not debug or (debug and cache is None)

        if cache is True:
            cache = self._cache

        _, _, _, channel = self.get_nslc(obj)
        station = self.get_station(self.get_nsl(obj))

        nslc = station.nsl() + (channel,)

        if self.is_blacklisted(nslc):
            raise NotFound(
                'waveform is blacklisted', nslc)

        if not self.is_whitelisted(nslc):
            raise NotFound(
                'waveform is not on whitelist', nslc)

        if tmin is not None:
            tmin = float(tmin)

        if tmax is not None:
            tmax = float(tmax)

        if cache is not None and (nslc, tmin, tmax) in cache:
            obj = cache[nslc, tmin, tmax]
            if isinstance(obj, Exception):
                raise obj
            else:
                return obj

        abs_delays = []
        for ocha in 'ENZRT':
            sc = self.station_corrections.get(station.nsl() + (channel,), None)
            if sc:
                abs_delays.append(abs(sc.delay))

        if abs_delays:
            abs_delay_max = max(abs_delays)
        else:
            abs_delay_max = 0.0

        projections = self._get_projections(
            station, backazimuth, source, target, tmin, tmax)

        try:
            trs_projected = []
            trs_restituted = []
            trs_raw = []
            for matrix, in_channels, out_channels in projections:
                deps = trace.project_dependencies(
                    matrix, in_channels, out_channels)

                trs_restituted_group = []
                trs_raw_group = []
                if channel in deps:
                    for cha in deps[channel]:
                        trs_restituted_this, trs_raw_this = \
                            self.get_waveform_restituted(
                                station.nsl() + (cha,),
                                quantity=quantity,
                                tmin=tmin, tmax=tmax, tpad=tpad+abs_delay_max,
                                toffset_noise_extract=0.0,
                                tfade=tfade,
                                freqlimits=freqlimits,
                                deltat=deltat,
                                want_incomplete=debug,
                                extend_incomplete=self.extend_incomplete)

                        trs_restituted_group.extend(trs_restituted_this)
                        trs_raw_group.extend(trs_raw_this)

                    trs_projected.extend(
                        trace.project(
                            trs_restituted_group, matrix,
                            in_channels, out_channels))

                    trs_restituted.extend(trs_restituted_group)
                    trs_raw.extend(trs_raw_group)

            for tr in trs_projected:
                sc = self.station_corrections.get(tr.nslc_id, None)
                if sc:
                    if self.apply_correction_factors:
                        tr.ydata /= sc.factor

                    if self.apply_correction_delays:
                        tr.shift(-sc.delay)

                if tmin is not None and tmax is not None:
                    tr.chop(tmin, tmax)

            if cache is not None:
                for tr in trs_projected:
                    cache[tr.nslc_id, tmin, tmax] = tr

            if debug:
                return trs_projected, trs_restituted, trs_raw

            for tr in trs_projected:
                if tr.channel == channel:
                    return tr

            raise NotFound(
                'waveform not available', station.nsl() + (channel,))

        except NotFound as e:
            if cache is not None:
                cache[nslc, tmin, tmax] = e
            raise

    def get_events(self, magmin=None, event_names=None):
        evs = []
        for ev in self.events:
            if ((magmin is None or ev.magnitude >= magmin) and
                    (event_names is None or ev.name in event_names)):
                evs.append(ev)

        return evs

    def get_event_by_time(self, t, magmin=None):
        evs = self.get_events(magmin=magmin)
        ev_x = None
        for ev in evs:
            if ev_x is None or abs(ev.time - t) < abs(ev_x.time - t):
                ev_x = ev

        if not ev_x:
            raise NotFound(
                'no event information matching criteria (t=%s, magmin=%s)' %
                (t, magmin))

        return ev_x

    def get_event(self):
        if self._event_name is None:
            raise NotFound('no main event selected in dataset')

        for ev in self.events:
            if ev.name == self._event_name:
                return ev

        raise NotFound('no such event: %s' % self._event_name)

    def get_picks(self):
        if self._picks is None:
            hash_to_name = {}
            names = set()
            for marker in self.pick_markers:
                if isinstance(marker, pmarker.EventMarker):
                    name = marker.get_event().name
                    if name in names:
                        raise DatasetError(
                            'duplicate event name "%s" in picks' % name)

                    names.add(name)
                    hash_to_name[marker.get_event_hash()] = name

            picks = {}
            for marker in self.pick_markers:
                if isinstance(marker, pmarker.PhaseMarker):
                    ehash = marker.get_event_hash()

                    nsl = marker.one_nslc()[:3]
                    phasename = marker.get_phasename()

                    if ehash is None or ehash not in hash_to_name:
                        raise DatasetError(
                            'unassociated pick %s.%s.%s, %s' %
                            (nsl + (phasename, )))

                    eventname = hash_to_name[ehash]

                    if (nsl, phasename, eventname) in picks:
                        raise DatasetError(
                            'duplicate pick %s.%s.%s, %s' %
                            (nsl + (phasename, )))

                    picks[nsl, phasename, eventname] = marker

            self._picks = picks

        return self._picks

    def get_pick(self, eventname, obj, phasename):
        nsl = self.get_nsl(obj)
        return self.get_picks().get((nsl, phasename, eventname), None)


class DatasetConfig(HasPaths):

    stations_path = Path.T(optional=True)
    stations_stationxml_paths = List.T(Path.T(), optional=True)
    events_path = Path.T(optional=True)
    waveform_paths = List.T(Path.T(), optional=True)
    clippings_path = Path.T(optional=True)
    responses_sacpz_path = Path.T(optional=True)
    responses_stationxml_paths = List.T(Path.T(), optional=True)
    station_corrections_path = Path.T(optional=True)
    apply_correction_factors = Bool.T(optional=True,
                                      default=True)
    apply_correction_delays = Bool.T(optional=True,
                                     default=True)
    extend_incomplete = Bool.T(default=False)
    picks_paths = List.T(Path.T())
    blacklist_paths = List.T(Path.T())
    blacklist = List.T(
        String.T(),
        help='stations/components to be excluded according to their STA, '
             'NET.STA, NET.STA.LOC, or NET.STA.LOC.CHA codes.')
    whitelist_paths = List.T(Path.T())
    whitelist = List.T(
        String.T(),
        optional=True,
        help='if not None, list of stations/components to include according '
             'to their STA, NET.STA, NET.STA.LOC, or NET.STA.LOC.CHA codes. '
             'Note: ''when whitelisting on channel level, both, the raw and '
             'the processed channel codes have to be listed.')

    def __init__(self, *args, **kwargs):
        HasPaths.__init__(self, *args, **kwargs)
        self._ds = {}

    def get_event_names(self):
        def extra(path):
            return expand_template(path, dict(
                event_name='*'))

        def fp(path):
            return self.expand_path(path, extra=extra)

        events = []
        for fn in glob.glob(fp(self.events_path)):
            events.extend(cached_load_events(fn))

        event_names = [ev.name for ev in events]
        return event_names

    def get_dataset(self, event_name):
        if event_name not in self._ds:
            def extra(path):
                return expand_template(path, dict(
                    event_name=event_name))

            def fp(path):
                return self.expand_path(path, extra=extra)

            ds = Dataset(event_name)
            ds.add_stations(
                pyrocko_stations_filename=fp(self.stations_path),
                stationxml_filenames=fp(self.stations_stationxml_paths))

            ds.add_events(filename=fp(self.events_path))

            if self.waveform_paths:
                ds.add_waveforms(paths=fp(self.waveform_paths))

            if self.clippings_path:
                ds.add_clippings(markers_filename=fp(self.clippings_path))

            if self.responses_sacpz_path:
                ds.add_responses(
                    sacpz_dirname=fp(self.responses_sacpz_path))

            if self.responses_stationxml_paths:
                ds.add_responses(
                    stationxml_filenames=fp(self.responses_stationxml_paths))

            if self.station_corrections_path:
                ds.add_station_corrections(
                    filename=fp(self.station_corrections_path))

            ds.apply_correction_factors = self.apply_correction_factors
            ds.apply_correction_delays = self.apply_correction_delays
            ds.extend_incomplete = self.extend_incomplete

            for picks_path in self.picks_paths:
                ds.add_picks(
                    filename=fp(picks_path))

            ds.add_blacklist(self.blacklist)
            ds.add_blacklist(filenames=fp(self.blacklist_paths))
            if self.whitelist:
                ds.add_whitelist(self.whitelist)
            if self.whitelist_paths:
                ds.add_whitelist(filenames=fp(self.whitelist_paths))

            self._ds[event_name] = ds

        return self._ds[event_name]


__all__ = '''
    Dataset
    DatasetConfig
    DatasetError
    InvalidObject
    NotFound
    StationCorrection
    load_station_corrections
    dump_station_corrections
'''.split()
