from .netcdf_generator import StaticDriverGen, SlurbDriverGen, CCTDriverGen
from .prepare_slurb_inputs import PrepareSlurbInputs
from .initialize_domain import InitializeDomainTask
from .gis_importer import GisImporter
from .finalize import FinalizeTask
from .cct_processing import CctProcessing
from .setup import SetupTask
from .trees_generator import LadGenerator, LaiGenerator
from .urban_atlas_osm import UrbanAtlasOSM
from .urban_atlas_dem_buildings import UrbanAtlasDemBuildings
from .finalize import FinalizeTask

class TaskFactory:
    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db
        # Registry of available task classes
        self._tasks = {
                "static_driver": StaticDriverGen,
                "slurb_driver": SlurbDriverGen,
                "cct_driver": CCTDriverGen,
                "prepare_slurb": PrepareSlurbInputs,
                "initialize_domain": InitializeDomainTask,
                "gis_import": GisImporter,
                "finalize": FinalizeTask,
                "cct_processing": CctProcessing,
                "lad": LadGenerator,
                "lai": LaiGenerator,
                "urban_atlas_osm": UrbanAtlasOSM,
                "urban_atlas_dem_buildings": UrbanAtlasDemBuildings,
                "setup": SetupTask
        }

    def get(self, task_key):
        """ Instantiates a task with the shared cfg and db automatically """
        task_class = self._tasks.get(task_key)
        if not task_class:
            raise ValueError(f"Task '{task_key}' not found in registry.")

        # Here we inject the repetitive arguments once
        return task_class(name=task_key, cfg=self.cfg, db=self.db)