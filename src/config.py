import os.path as op
from pyrocko import gf
from pyrocko.guts import Bool, List, load, dump

from wafe import dataset, meta, measure

guts_prefix = 'wafe'


class EngineConfig(meta.HasPaths):
    gf_stores_from_pyrocko_config = Bool.T(default=True)
    gf_store_superdirs = List.T(meta.Path.T())
    gf_store_dirs = List.T(meta.Path.T())

    def __init__(self, *args, **kwargs):
        meta.HasPaths.__init__(self, *args, **kwargs)
        self._engine = None

    def get_engine(self):
        if self._engine is None:
            fp = self.expand_path
            self._engine = gf.LocalEngine(
                use_config=self.gf_stores_from_pyrocko_config,
                store_superdirs=fp(self.gf_store_superdirs),
                store_dirs=fp(self.gf_store_dirs))

        return self._engine


class Config(meta.HasPaths):
    dataset_config = dataset.DatasetConfig.T()
    measures = List.T(measure.FeatureMeasure.T())
    store_id = gf.StringID.T()
    engine_config = EngineConfig.T()
    output_path = meta.Path.T()

    def __init__(self, *args, **kwargs):
        meta.HasPaths.__init__(self, *args, **kwargs)
        self._config_name = 'untitled'

    def set_config_name(self, config_name):
        self._config_name = config_name

    def expand_path(self, path):
        def extra(path):
            return meta.expand_template(path, dict(
                config_name=self._config_name))

        return meta.HasPaths.expand_path(self, path, extra=extra)

    def get_event_names(self):
        return self.dataset_config.get_event_names()

    def get_dataset(self, event_name):
        return self.dataset_config.get_dataset(event_name)

    def get_engine(self):
        return self.engine_config.get_engine()


def read_config(path):
    try:
        config = load(filename=path)
    except FileNotFoundError as e:
        raise meta.WafeError(str(e))

    if not isinstance(config, Config):
        raise meta.WafeError('invalid Wafe configuration in file "%s"' % path)

    config.set_basepath(op.dirname(path) or '.')
    config.set_config_name(op.splitext(op.basename(path))[0])

    return config


def write_config(config, path):
    basepath = config.get_basepath()
    dirname = op.dirname(path) or '.'
    config.change_basepath(dirname)
    dump(config, filename=path)
    config.change_basepath(basepath)
