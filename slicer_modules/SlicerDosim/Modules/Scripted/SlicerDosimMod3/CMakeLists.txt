#-----------------------------------------------------------------------------
set(MODULE_NAME SlicerDosimMod3)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  __init__.py
  SlicerDosimMod3.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/UI/SlicerDosimMod3.ui
  Resources/UI/Icons/SlicerDosimMod3.svg
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  )
