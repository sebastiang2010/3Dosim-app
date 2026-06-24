"""Libreria interna del modulo SlicerDosim."""

from .segmentation import LiverSegmenter
from .registration import DosimetryRegistration
from .mcnp_generator import MCNPInputGenerator
from .dosimetry import DoseCalculator
from .dvh_analysis import DVHAnalyzer
from .utils import SlicerDosimUtils
from .phantom_segmentation import PhantomSegmenter

from .config import TissueConfig
from .mcnp_materials import MCNPMaterialMapper
from .mcnp_geometry import MCNPGeometryBuilder
from .mcnp_source import MCNPSourceBuilder
from .mcnp_tallies import MCNPTallyBuilder
from .mctal_parser import MCTALParser

# El orquestador IA principal esta en PipelineOrchestrator/ai_supervisor.py
# (el orquestador legacy de SlicerDosimLib se elimino en v4)
