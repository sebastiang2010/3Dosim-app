"""Test rapido para verificar disponibilidad de BRAINSResample y diagnostico de resample."""
import sys

def check_brains():
    try:
        import slicer
        print(f"Slicer version: {slicer.app.majorVersion}.{slicer.app.minorVersion}")
        
        # 1. Verificar si el modulo existe
        brains = getattr(slicer.modules, 'brainsresample', None)
        if brains is None:
            print("[FAIL] slicer.modules.brainsresample NO existe")
            # Listar CLI modules disponibles
            cli_modules = [name for name in dir(slicer.modules) if not name.startswith('_')]
            print(f"  Modulos disponibles: {[m for m in cli_modules if 'brain' in m.lower() or 'elastix' in m.lower()]}")
            return False
        else:
            print(f"[OK] slicer.modules.brainsresample encontrado: {brains}")
        
        # 2. Buscar nodos en escena
        ct_nodes = [n for n in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") 
                    if "CT" in n.GetName().upper()]
        pet_nodes = [n for n in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") 
                     if "PET" in n.GetName().upper()]
        
        print(f"Nodos CT: {[(n.GetName(), n.GetImageData().GetDimensions(), n.GetSpacing()) for n in ct_nodes]}")
        print(f"Nodos PET: {[(n.GetName(), n.GetImageData().GetDimensions(), n.GetSpacing()) for n in pet_nodes]}")
        
        # 3. Probar BRAINS CLI
        if ct_nodes and pet_nodes:
            ct = ct_nodes[0]
            pet = pet_nodes[0]
            print(f"\nProbando BRAINSResample...")
            print(f"  inputVolume: {pet.GetID()} ({pet.GetName()})")
            print(f"  referenceVolume: {ct.GetID()} ({ct.GetName()})")
            
            test_out = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TEST_BRAINS")
            params = {
                'inputVolume': pet.GetID(),
                'referenceVolume': ct.GetID(),
                'outputVolume': test_out.GetID(),
                'pixelType': 'float',
                'interpolationMode': 'NearestNeighbor',
            }
            try:
                slicer.cli.run(slicer.modules.brainsresample, None, params, wait_for_completion=True)
                if test_out.GetImageData() is None:
                    print("[FAIL] BRAINS devolvio nodo sin datos")
                else:
                    d = test_out.GetImageData().GetDimensions()
                    s = test_out.GetSpacing()
                    print(f"[OK] BRAINS exitoso: {d[0]}x{d[1]}x{d[2]}, spacing {s[0]:.3f}x{s[1]:.3f}x{s[2]:.3f}")
            except Exception as e:
                print(f"[FAIL] BRAINS lanzo excepcion: {e}")
            finally:
                slicer.mrmlScene.RemoveNode(test_out)
        
        return True
    except Exception as e:
        print(f"[FAIL] Error general: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    ok = check_brains()
    print(f"\nResultado: {'OK' if ok else 'FAIL'}")
    if not ok:
        sys.exit(1)
