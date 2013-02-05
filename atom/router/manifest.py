import os
import json



class ModuleManifest(object):
    def __init__(self, module_path):
        filename = os.path.join(module_path, 'module.manifest')
        
        try:
            with open(filename, 'r') as f:
                manifest = json.load(f)
        except StandardError as e:
            raise ModuleManifestError('unable to read manifest file: {}'.format(e))
        
        for key in ('type',):
            if key not in manifest:
                raise ModuleManifestError('manifest missing "{}" key'.format(key))
        self.type = manifest['type']
        
        if self.type not in ('system', 'unix'):
            raise ModuleManifestError('unknown module type: {}'.format(self.type))
        
        if self.type == 'system':
            raise NotImplementedError()
        
        if self.type == 'unix':
            for key in ('command',):
                if key not in manifest:
                    raise ModuleManifestError('manifest missing "{}" key'.format(key))
            
            self.command = manifest['command']

class ModuleManifestError(Exception):
    pass