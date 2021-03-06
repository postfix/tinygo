#!/usr/bin/python3

import sys
import os
from xml.dom import minidom
from glob import glob
from collections import OrderedDict
import re

ARM_ARCHS = {
    'CM0': 'armv6m',
    'CM4': 'armv7em',
}

class Device:
    # dummy
    pass

def getText(element):
    strings = []
    for node in element.childNodes:
        if node.nodeType == node.TEXT_NODE:
            strings.append(node.data)
    return ''.join(strings)

def formatText(text):
    text = re.sub('[ \t\n]+', ' ', text) # Collapse whitespace (like in HTML)
    text = text.replace('\\n ', '\n')
    text = text.strip()
    return text

def readSVD(path):
    # Read ARM SVD files.
    device = Device()
    xml = minidom.parse(path)
    root = xml.getElementsByTagName('device')[0]
    deviceName = getText(root.getElementsByTagName('name')[0])
    deviceDescription = getText(root.getElementsByTagName('description')[0])
    licenseText = formatText(getText(root.getElementsByTagName('licenseText')[0]))
    cpu = root.getElementsByTagName('cpu')[0]
    cpuName = getText(cpu.getElementsByTagName('name')[0])

    device.peripherals = []

    interrupts = OrderedDict()

    for periphEl in root.getElementsByTagName('peripherals')[0].getElementsByTagName('peripheral'):
        name = getText(periphEl.getElementsByTagName('name')[0])
        description = getText(periphEl.getElementsByTagName('description')[0])
        baseAddress = int(getText(periphEl.getElementsByTagName('baseAddress')[0]), 0)

        peripheral = {
            'name':        name,
            'description': description,
            'registers':   [],
        }
        device.peripherals.append(peripheral)

        for interrupt in periphEl.getElementsByTagName('interrupt'):
            intrName = getText(interrupt.getElementsByTagName('name')[0])
            intrIndex = int(getText(interrupt.getElementsByTagName('value')[0]))
            if intrName in interrupts:
                if interrupts[intrName]['index'] != intrIndex:
                    raise ValueError('interrupt with the same name has different indexes: ' + intrName)
                interrupts[intrName]['description'] += ' // ' + description
            else:
                interrupts[intrName] = {
                    'name':        intrName,
                    'index':       intrIndex,
                    'description': description,
                }

        regsEls = periphEl.getElementsByTagName('registers')
        if regsEls:
            for el in regsEls[0].childNodes:
                if el.nodeName == 'register':
                    peripheral['registers'].append(parseSVDRegister(name, el, baseAddress))
                elif el.nodeName == 'cluster':
                    if el.getElementsByTagName('dim'):
                        continue # TODO
                    clusterPrefix = getText(el.getElementsByTagName('name')[0]) + '_'
                    clusterOffset = int(getText(el.getElementsByTagName('addressOffset')[0]), 0)
                    for regEl in el.childNodes:
                        if regEl.nodeName == 'register':
                            peripheral['registers'].append(parseSVDRegister(name, regEl, baseAddress + clusterOffset, clusterPrefix))
                else:
                    continue

    device.interrupts = interrupts.values() # TODO: sort by index
    device.metadata = {
        'file':             os.path.basename(path),
        'descriptorSource': 'https://github.com/NordicSemiconductor/nrfx/tree/master/mdk',
        'name':             deviceName,
        'nameLower':        deviceName.lower(),
        'description':      deviceDescription,
        'licenseBlock':     '\n//     ' + licenseText.replace('\n', '\n//     '),
        'regType':          'uint32',
        'arch':             ARM_ARCHS[cpuName],
        'family':           getText(root.getElementsByTagName('series')[0]),
    }

    return device

def parseSVDRegister(peripheralName, regEl, baseAddress, namePrefix=''):
    regName = getText(regEl.getElementsByTagName('name')[0])
    regDescription = getText(regEl.getElementsByTagName('description')[0])
    offsetEls = regEl.getElementsByTagName('offset')
    if not offsetEls:
        offsetEls = regEl.getElementsByTagName('addressOffset')
    address = baseAddress + int(getText(offsetEls[0]), 0)

    dimEls = regEl.getElementsByTagName('dim')
    array = None
    if dimEls:
        array = int(getText(dimEls[0]), 0)
        regName = regName.replace('[%s]', '')

    fields = []
    fieldsEls = regEl.getElementsByTagName('fields')
    if fieldsEls:
        for fieldEl in fieldsEls[0].childNodes:
            if fieldEl.nodeName != 'field':
                continue
            fieldName = getText(fieldEl.getElementsByTagName('name')[0])
            descrEls = fieldEl.getElementsByTagName('description')
            for enumEl in fieldEl.getElementsByTagName('enumeratedValue'):
                enumName = getText(enumEl.getElementsByTagName('name')[0])
                enumDescription = getText(enumEl.getElementsByTagName('description')[0])
                enumValue = int(getText(enumEl.getElementsByTagName('value')[0]), 0)
                fields.append({
                    'name':        '{}_{}{}_{}_{}'.format(peripheralName, namePrefix, regName, fieldName, enumName),
                    'description': enumDescription,
                    'value':       enumValue,
                })

    return {
        'variants': [{
            'name':    namePrefix + regName,
            'address': address,
        }],
        'description': regDescription.replace('\n', ' '),
        'bitfields':   fields,
        'array':       array,
    }

def readATDF(path):
    # Read Atmel device descriptor files.
    # See: http://packs.download.atmel.com

    device = Device()

    xml = minidom.parse(path)
    device = xml.getElementsByTagName('device')[0]
    deviceName = device.getAttribute('name')
    arch = device.getAttribute('architecture')
    family = device.getAttribute('family')

    memorySizes = {}
    for el in device.getElementsByTagName('address-space'):
        addressSpace = {
            'size': int(el.getAttribute('size'), 0),
            'segments': {},
        }
        memorySizes[el.getAttribute('name')] = addressSpace
        for segmentEl in el.getElementsByTagName('memory-segment'):
            addressSpace['segments'][segmentEl.getAttribute('name')] = int(segmentEl.getAttribute('size'), 0)

    device.interrupts = []
    for el in device.getElementsByTagName('interrupts')[0].getElementsByTagName('interrupt'):
        device.interrupts.append({
            'index':       int(el.getAttribute('index')),
            'name':        el.getAttribute('name'),
            'description': el.getAttribute('caption'),
        })

    allRegisters = {}
    commonRegisters = {}

    device.peripherals = []
    for el in xml.getElementsByTagName('modules')[0].getElementsByTagName('module'):
        peripheral = {
            'name':        el.getAttribute('name'),
            'description': el.getAttribute('caption'),
            'registers':   [],
        }
        device.peripherals.append(peripheral)
        for regElGroup in el.getElementsByTagName('register-group'):
            for regEl in regElGroup.getElementsByTagName('register'):
                size = int(regEl.getAttribute('size'))
                regName = regEl.getAttribute('name')
                regOffset = int(regEl.getAttribute('offset'), 0)
                reg = {
                    'description': regEl.getAttribute('caption'),
                    'bitfields':   [],
                    'array':       None,
                }
                if size == 1:
                    reg['variants'] = [{
                        'name':    regName,
                        'address': regOffset,
                    }]
                elif size == 2:
                    reg['variants'] = [{
                        'name':    regName + 'L',
                        'address': regOffset,
                    }, {
                        'name':    regName + 'H',
                        'address': regOffset,
                    }]
                else:
                    reg['variants'] = [] # TODO

                for bitfieldEl in regEl.getElementsByTagName('bitfield'):
                    reg['bitfields'].append({
                        'name':        regName + '_' + bitfieldEl.getAttribute('name'),
                        'description': bitfieldEl.getAttribute('caption'),
                        'value':       int(bitfieldEl.getAttribute('mask'), 0),
                    })

                if regName in allRegisters:
                    firstReg = allRegisters[regName]
                    if firstReg['register'] in firstReg['peripheral']['registers']:
                        firstReg['peripheral']['registers'].remove(firstReg['register'])
                    if firstReg['address'] != regOffset:
                        continue # TODO
                    commonRegisters = allRegisters[regName]['register']
                    continue
                else:
                    allRegisters[regName] = {'address': regOffset, 'register': reg, 'peripheral': peripheral}

                peripheral['registers'].append(reg)

    device.metadata = {
        'file':             os.path.basename(path),
        'descriptorSource': 'http://packs.download.atmel.com/',
        'name':             deviceName,
        'nameLower':        deviceName.lower(),
        'description':      'Device information for the {}.'.format(deviceName),
        'licenseBlock':     '',
        'regType':          'uint8',
        'arch':             arch,
        'family':           family,
        'flashSize':        memorySizes['prog']['size'],
        'ramSize':          memorySizes['data']['segments'].get('IRAM', memorySizes['data']['segments'].get('INTERNAL_SRAM')),
        'numInterrupts':    len(device.interrupts),
    }

    return device

def writeGo(outdir, device):
    # The Go module for this device.
    out = open(outdir + '/' + device.metadata['nameLower'] + '.go', 'w')
    pkgName = os.path.basename(outdir.rstrip('/'))
    out.write('''\
// Automatically generated file. DO NOT EDIT.
// Generated by gen-device.py from {file}, see {descriptorSource}

// +build {pkgName},{nameLower}

// {description}
// {licenseBlock}
package {pkgName}

// Magic type name for the compiler.
type __reg {regType}

// Export this magic type name.
type RegValue = __reg

// Some information about this device.
const (
	DEVICE     = "{name}"
	ARCH       = "{arch}"
	FAMILY     = "{family}"
)
'''.format(pkgName=pkgName, **device.metadata))

    out.write('\n// Interrupts\nconst (\n')
    for intr in device.interrupts:
        out.write('\tIRQ_{name} = {index} // {description}\n'.format(**intr))
    intrMax = max(map(lambda intr: intr['index'], device.interrupts))
    out.write('\tIRQ_max = {} // Highest interrupt number on this device.\n'.format(intrMax))
    out.write(')\n')

    out.write('\n// Peripherals\nvar (')
    for peripheral in device.peripherals:
        out.write('\n\t// {description}\n\t{name} = struct {{\n'.format(**peripheral))
        for register in peripheral['registers']:
            for variant in register['variants']:
                regType = '__reg'
                if register['array'] is not None:
                    regType = '[{}]__reg'.format(register['array'])
                out.write('\t\t{name} {regType}\n'.format(**variant, regType=regType))
        out.write('\t}{\n')
        for register in peripheral['registers']:
            for variant in register['variants']:
                out.write('\t\t{name}: '.format(**variant))
                if register['array'] is not None:
                    out.write('[{num}]__reg{{'.format(num=register['array']))
                    if register['description']:
                        out.write(' // {description}'.format(**register))
                    out.write('\n')
                    for i in range(register['array']):
                        out.write('\t\t\t0x{:x},\n'.format(variant['address'] + i * 4)) # TODO: pointer width
                    out.write('\t\t},')
                else:
                    out.write('0x{address:x},'.format(**variant))
                    if register['description']:
                        out.write(' // {description}'.format(**register))
                out.write('\n')
        out.write('\t}\n')
    out.write(')\n')

    for peripheral in device.peripherals:
        if not sum(map(lambda r: len(r['bitfields']), peripheral['registers'])): continue
        out.write('\n// Bitfields for {name}: {description}\nconst('.format(**peripheral))
        for register in peripheral['registers']:
            if not register['bitfields']: continue
            for variant in register['variants']:
                out.write('\n\t// {name}'.format(**variant))
                if register['description']:
                    out.write(': {description}'.format(**register))
                out.write('\n')
            for bitfield in register['bitfields']:
                out.write('\t{name} = 0x{value:x}'.format(**bitfield))
                if bitfield['description']:
                    out.write('// {description}'.format(**bitfield))
                out.write('\n')
        out.write(')\n')

def writeLD(outdir, device):
    # Variables for the linker script.
    out = open(outdir + '/' + device.metadata['nameLower'] + '.ld', 'w')
    out.write('''\
/* Automatically generated file. DO NOT EDIT. */
/* Generated by gen-device.py from {file}, see {descriptorSource} */

__flash_size = 0x{flashSize:x};
__ram_size   = 0x{ramSize:x};
__num_isrs   = {numInterrupts};
'''.format(**device.metadata))
    out.close()


def generate(indir, outdir):
    for filepath in glob(indir + '/*.svd'):
        print(filepath)
        device = readSVD(filepath)
        writeGo(outdir, device)

    for filepath in glob(indir + '/*.atdf'):
        print(filepath)
        device = readATDF(filepath)
        writeGo(outdir, device)
        writeLD(outdir, device)


if __name__ == '__main__':
    indir = sys.argv[1] # directory with register descriptor files (*.svd, *.atdf)
    outdir = sys.argv[2] # output directory
    generate(indir, outdir)
