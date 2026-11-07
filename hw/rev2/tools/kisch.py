"""Minimal KiCad 10 schematic sheet generator.

Sheets are described as data: each part is a library symbol, placed on a grid,
with a pin -> net mapping. Every pin gets a label (or a power symbol for
power nets) exactly on its connection point, so connectivity comes from the
data, not from hand-drawn wires. The result is checked by exporting the
netlist with kicad-cli (see verify.py).

Net naming conventions:
  - names listed in Sheet.power_nets  -> power symbol (global net)
  - names starting with "/"           -> hierarchical label (without the "/"),
                                         must match a sheet pin in the root
  - names starting with "@"           -> global label (without the "@")
  - None                              -> no-connect flag
  - anything else                     -> local label
"""
import re
import uuid as _uuid

KICAD_SYMBOLS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/"
GRID = 2.54


def new_uuid():
    return str(_uuid.uuid4())


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# S-expression helpers working on raw text blocks of library files.

def _block_end(text, start):
    """Index just after the s-expression starting at text[start] == '('."""
    depth = 0
    i = start
    in_str = False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced s-expression")


def _top_symbol_block(text, name):
    m = re.search(r'\n\t\(symbol ' + re.escape(q(name)) + r'\n', text)
    if not m:
        raise KeyError(name)
    start = m.start() + 2
    return text[start:_block_end(text, start)]


class LibSymbol:
    """A library symbol definition, flattened (no 'extends')."""

    def __init__(self, lib_id, block):
        self.lib_id = lib_id
        self.block = block
        self.pins = self._parse_pins()

    @classmethod
    def from_kicad_lib(cls, lib, name, rename=None):
        text = open(KICAD_SYMBOLS + lib + ".kicad_sym").read()
        block = _top_symbol_block(text, name)
        ext = re.search(r'\(extends "([^"]+)"\)', block)
        if ext:
            parent = _top_symbol_block(text, ext.group(1))
            block = cls._flatten(parent, block, ext.group(1), name)
        new_name = rename or name
        if new_name != name:
            block = cls._rename(block, name, new_name)
        return cls(lib + ":" + new_name, block)

    @classmethod
    def from_schematic(cls, path, embedded_name, lib_id):
        """Take a symbol embedded in an existing schematic's lib_symbols."""
        text = open(path).read()
        m = re.search(r'\n\t\t\(symbol ' + re.escape(q(embedded_name)) + r'\n', text)
        if not m:
            raise KeyError(embedded_name)
        start = m.start() + 3
        block = text[start:_block_end(text, start)]
        block = re.sub(r'^(\t+)', lambda mm: mm.group(1)[1:], block, flags=re.M)
        short = lib_id.split(":", 1)[1]
        block = cls._rename(block, embedded_name, short)
        return cls(lib_id, block)

    @staticmethod
    def _rename(block, old, new):
        block = block.replace("(symbol " + q(old), "(symbol " + q(new), 1)
        return re.sub(r'\(symbol "' + re.escape(old) + r'_(\d+)_(\d+)"',
                      lambda m: '(symbol "%s_%s_%s"' % (new, m.group(1), m.group(2)), block)

    @staticmethod
    def _flatten(parent, child, parent_name, child_name):
        """Child properties + parent graphics/pins."""
        props = re.findall(r'\n\t\t\(property .*?(?=\n\t\t\((?:property|symbol|embedded|exclude|in_bom|on_board)|\n\t\)$)',
                           child, re.S)
        body = LibSymbol._rename(parent, parent_name, child_name)
        body = re.sub(r'\n\t\t\(property .*?(?=\n\t\t\((?:property|symbol|embedded|exclude|in_bom|on_board|power|pin_|duplicate)|\n\t\)$)',
                      "", body, flags=re.S)
        insert = body.index("\n\t\t(symbol ")
        return body[:insert] + "".join(props) + body[insert:]

    def _parse_pins(self):
        pins = []
        for sub in re.finditer(r'\n\t\t\(symbol "[^"]*_(\d+)_(\d+)"', self.block):
            start = sub.start() + 3
            sblock = self.block[start:_block_end(self.block, start)]
            unit = int(sub.group(1))
            for pm in re.finditer(r'\(pin (\w+) \w+\s+\(at ([-\d.]+) ([-\d.]+) (\d+)\)\s+\(length ([\d.]+)\)', sblock):
                pstart = pm.start()
                pblock = sblock[pstart:_block_end(sblock, pstart)]
                name = re.search(r'\(name "((?:[^"\\]|\\.)*)"', pblock).group(1)
                number = re.search(r'\(number "((?:[^"\\]|\\.)*)"', pblock).group(1)
                hidden = "(hide yes)" in pblock.split("(name")[0]
                pins.append(dict(unit=unit, type=pm.group(1), x=float(pm.group(2)),
                                 y=float(pm.group(3)), angle=int(pm.group(4)),
                                 name=name, number=number, hidden=hidden))
        return pins

    def units(self):
        return sorted({p["unit"] for p in self.pins if p["unit"] > 0}) or [1]

    def pin_numbers(self):
        return {p["number"] for p in self.pins}

    def embedded(self):
        """Block as stored in a schematic's lib_symbols (name = lib_id)."""
        short = self.lib_id.split(":", 1)[1]
        b = self.block.replace("(symbol " + q(short), "(symbol " + q(self.lib_id), 1)
        return "\n".join("\t" + l for l in b.split("\n"))


# ---------------------------------------------------------------------------

def _fmt(v):
    v = round(v, 4)
    return ("%d" % v) if v == int(v) else ("%g" % v)


LABEL_ANGLE = {0: 180, 180: 0, 90: 270, 270: 90}


class Sheet:
    def __init__(self, title, instance_path, project="Scaffold", paper="A2",
                 power_nets=(), sheet_uuid=None):
        self.title = title
        self.instance_path = instance_path
        self.project = project
        self.paper = paper
        self.power_nets = set(power_nets) | {"GND"}
        self.uuid = sheet_uuid or new_uuid()
        self.libs = {}
        self.items = []
        self.parts = {}      # ref -> dict(sym, nets, value, fields)
        self.pwr_count = 0
        self._power_syms()

    def _power_syms(self):
        self.libs["power:GND"] = LibSymbol.from_kicad_lib("power", "GND")
        self.libs["power:VCC"] = LibSymbol.from_kicad_lib("power", "VCC")
        self.libs["power:PWR_FLAG"] = LibSymbol.from_kicad_lib("power", "PWR_FLAG")

    # -- text items -------------------------------------------------------
    def text(self, s, x, y, size=2.5):
        self.items.append('\t(text %s\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n'
                          '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
                          '\t\t(uuid %s)\n\t)' % (q(s), _fmt(x), _fmt(y), size, size, q(new_uuid())))

    def _label(self, net, x, y, angle):
        just = "left" if angle in (0, 90) else "right"
        eff = '(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify %s)\n\t\t)' % just
        if net.startswith("/"):
            self.items.append('\t(hierarchical_label %s\n\t\t(shape bidirectional)\n\t\t(at %s %s %d)\n\t\t%s\n\t\t(uuid %s)\n\t)'
                              % (q(net[1:]), _fmt(x), _fmt(y), angle, eff, q(new_uuid())))
        elif net.startswith("@"):
            self.items.append('\t(global_label %s\n\t\t(shape bidirectional)\n\t\t(at %s %s %d)\n\t\t(fields_autoplaced yes)\n\t\t%s\n\t\t(uuid %s)\n\t)'
                              % (q(net[1:]), _fmt(x), _fmt(y), angle, eff, q(new_uuid())))
        else:
            self.items.append('\t(label %s\n\t\t(at %s %s %d)\n\t\t%s\n\t\t(uuid %s)\n\t)'
                              % (q(net), _fmt(x), _fmt(y), angle, eff, q(new_uuid())))

    def _no_connect(self, x, y):
        self.items.append('\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid %s)\n\t)' % (_fmt(x), _fmt(y), q(new_uuid())))

    def _power(self, net, x, y, label_angle):
        self.pwr_count += 1
        if net == "GND":
            lib = "power:GND"
            rot = {270: 0, 90: 180, 180: 270, 0: 90}[label_angle]
        else:
            lib = "power:VCC"
            rot = {90: 0, 270: 180, 180: 90, 0: 270}[label_angle]
        ref = "#PWR%s%03d" % (self.title[:3].upper(), self.pwr_count)
        self._symbol_instance(lib, ref, net, "", x, y, rot, 1, {}, in_bom=False)

    # -- symbols ----------------------------------------------------------
    def _symbol_instance(self, lib_id, ref, value, footprint, x, y, rot, unit, fields, in_bom=True, dnp=False):
        u = new_uuid()
        props = [("Reference", ref, False), ("Value", value, False),
                 ("Footprint", footprint, True), ("Datasheet", "", True)]
        props += [(k, v, True) for k, v in fields.items()]
        ptxt = ""
        for i, (k, v, hide) in enumerate(props):
            ox, oy = (x + 3.0, y - 2.0 + 2.0 * i) if i < 2 else (x, y)
            ptxt += ('\t\t(property %s %s\n\t\t\t(at %s %s 0)\n%s\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)\n'
                     % (q(k), q(v), _fmt(ox), _fmt(oy), "\t\t\t(hide yes)\n" if (hide or ref.startswith("#")) and k != "Value" else ""))
        pin_uuids = "".join('\t\t(pin %s\n\t\t\t(uuid %s)\n\t\t)\n' % (q(p["number"]), q(new_uuid()))
                            for p in self.libs[lib_id].pins if p["unit"] in (0, unit))
        self.items.append(
            '\t(symbol\n\t\t(lib_id %s)\n\t\t(at %s %s %d)\n\t\t(unit %d)\n\t\t(exclude_from_sim no)\n'
            '\t\t(in_bom %s)\n\t\t(on_board %s)\n\t\t(dnp %s)\n\t\t(uuid %s)\n%s%s'
            '\t\t(instances\n\t\t\t(project %s\n\t\t\t\t(path %s\n\t\t\t\t\t(reference %s)\n\t\t\t\t\t(unit %d)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)'
            % (q(lib_id), _fmt(x), _fmt(y), rot, unit, "yes" if in_bom else "no",
               "yes" if in_bom else "no", "yes" if dnp else "no", q(u), ptxt, pin_uuids,
               q(self.project), q(self.instance_path), q(ref), unit))

    def add(self, ref, sym, nets, at, value="", footprint="", fields=None, unit=None, dnp=False):
        """Place a symbol (all units, or one unit) and label its pins.

        nets: {pin number: net name or None for no-connect}. Every pin of
        the placed unit(s) must be listed (unused pins explicitly as None),
        except hidden pins and pins listed in sym.pins with the same number
        (stacked pins), which share the entry.
        """
        self.libs[sym.lib_id] = sym
        fields = dict(fields or {})
        units = [unit] if unit else sym.units()
        part = self.parts.setdefault(ref, dict(sym=sym, nets={}, value=value, fields=fields,
                                               footprint=footprint, dnp=dnp))
        x0, y0 = at
        for i, un in enumerate(units):
            ux = x0 + i * 80 if not unit else x0
            self._symbol_instance(sym.lib_id, ref, value, footprint, ux, y0, 0, un, fields, dnp=dnp)
            done = set()
            for p in sym.pins:
                if p["unit"] not in (0, un):
                    continue
                key = (p["number"], p["x"], p["y"])
                if key in done:
                    continue
                done.add(key)
                if p["number"] not in nets:
                    raise KeyError("%s: pin %s (%s) not assigned" % (ref, p["number"], p["name"]))
                net = nets[p["number"]]
                part["nets"][p["number"]] = net
                px, py = ux + p["x"], y0 - p["y"]
                la = LABEL_ANGLE[p["angle"]]
                if net is None:
                    self._no_connect(px, py)
                elif net in self.power_nets:
                    self._power(net, px, py, la)
                else:
                    self._label(net, px, py, la)
        extra = set(nets) - sym.pin_numbers()
        if extra:
            raise KeyError("%s: unknown pins %s" % (ref, sorted(extra)))

    def power_flags(self, nets, x, y, step=12.7):
        """PWR_FLAG markers for rails driven through passive parts."""
        for i, net in enumerate(nets):
            fx = round((x + i * step) / GRID) * GRID
            fy = round(y / GRID) * GRID
            self.pwr_count += 1
            self._symbol_instance("power:PWR_FLAG", "#FLG%s%03d" % (self.title[:3].upper(), self.pwr_count),
                                  "PWR_FLAG", "", fx, fy, 0, 1, {}, in_bom=False)
            # PWR_FLAG pin is at its origin, pointing down: hang the net below.
            if net in self.power_nets:
                self._power(net, fx, fy, 270)
            else:
                self._label(net, fx, fy, 270)

    # -- output -----------------------------------------------------------
    def render(self):
        libs = "\n".join(s.embedded() for _, s in sorted(self.libs.items()))
        return ('(kicad_sch\n\t(version 20260306)\n\t(generator "scaffold_kisch")\n\t(generator_version "10.0")\n'
                '\t(uuid %s)\n\t(paper %s)\n\t(title_block\n\t\t(title %s)\n\t\t(company "Scaffold")\n\t\t(rev "2.0")\n\t)\n'
                '\t(lib_symbols\n%s\n\t)\n%s\n\t(embedded_fonts no)\n)\n'
                % (q(self.uuid), q(self.paper), q(self.title), libs, "\n".join(self.items)))

    def write(self, path):
        open(path, "w").write(self.render())


# ---------------------------------------------------------------------------
# Simple rectangular symbols for parts missing from the KiCad libraries.

def box_symbol(lib_id, left, right, top=(), bottom=(), footprint="", ref="U", pin_len=2.54):
    """left/right/top/bottom: lists of (number, name, type); None = gap."""
    short = lib_id.split(":", 1)[1]
    n = max(len(left), len(right), 1)
    w = max(len(top), len(bottom), 4) * GRID + 2 * GRID
    w = max(w, 15.24)
    h = (n + 1) * GRID
    def snap(v):
        return round(v / GRID) * GRID

    # Box edges on the grid, pins at exact grid steps from the top edge.
    x0, x1 = -snap(w / 2), snap(w / 2)
    y0 = snap(h / 2)
    y1 = y0 - (n + 1) * GRID
    pins = []

    def pin(num, name, typ, x, y, ang):
        pins.append('\t\t\t(pin %s line\n\t\t\t\t(at %s %s %d)\n\t\t\t\t(length %s)\n'
                    '\t\t\t\t(name %s\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n'
                    '\t\t\t\t(number %s\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)'
                    % (typ, _fmt(x), _fmt(y), ang, _fmt(pin_len), q(name), q(num)))

    for i, p in enumerate(left):
        if p:
            pin(p[0], p[1], p[2], x0 - pin_len, y0 - (i + 1) * GRID, 0)
    for i, p in enumerate(right):
        if p:
            pin(p[0], p[1], p[2], x1 + pin_len, y0 - (i + 1) * GRID, 180)
    for i, p in enumerate(top):
        if p:
            pin(p[0], p[1], p[2], x0 + (i + 1) * GRID, y0 + pin_len, 270)
    for i, p in enumerate(bottom):
        if p:
            pin(p[0], p[1], p[2], x0 + (i + 1) * GRID, y1 - pin_len, 90)
    sx0, sx1, sy0, sy1 = x0, x1, y0, y1

    def prop(k, v, y, hide):
        return ('\t\t(property %s %s\n\t\t\t(at 0 %s 0)\n%s\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                % (q(k), q(v), _fmt(y), "\t\t\t(hide yes)\n" if hide else ""))
    block = ('(symbol %s\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n%s%s%s%s'
             '\t\t(symbol %s\n\t\t\t(rectangle\n\t\t\t\t(start %s %s)\n\t\t\t\t(end %s %s)\n\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n'
             '\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
             '\t\t(symbol %s\n%s\n\t\t)\n\t)'
             % (q(short), prop("Reference", ref, sy0 + 1.27, False), prop("Value", short, sy1 - 1.27, False),
                prop("Footprint", footprint, 0, True), prop("Datasheet", "", 0, True),
                q(short + "_0_1"), _fmt(sx0), _fmt(sy0), _fmt(sx1), _fmt(sy1),
                q(short + "_1_1"), "\n".join(pins)))
    return LibSymbol(lib_id, block)


def symbol_extent(sym, unit=None):
    xs = [p["x"] for p in sym.pins if unit is None or p["unit"] in (0, unit)] or [0]
    ys = [p["y"] for p in sym.pins if unit is None or p["unit"] in (0, unit)] or [0]
    return min(xs), max(xs), min(ys), max(ys)


class Grid:
    """Places parts in rows inside a rectangular region of the sheet."""

    def __init__(self, sheet, x, y, width, title=None, row_gap=12.7):
        self.sheet = sheet
        self.x0 = round(x / GRID) * GRID
        self.x = self.x0
        self.y = round(y / GRID) * GRID
        self.xmax = x + width
        self.row_h = 0
        self.row_gap = row_gap
        if title:
            sheet.text(title, self.x0, self.y - 2.54 * 3, size=2.5)

    def add(self, ref, sym, nets, unit=None, label_room=20.32, **kw):
        xmin, xmax, ymin, ymax = symbol_extent(sym, unit)
        w = (xmax - xmin) + 2 * label_room
        h = (ymax - ymin) + 2 * 7.62
        if self.x + w > self.xmax and self.x > self.x0:
            self.x = self.x0
            self.y += self.row_h + self.row_gap
            self.row_h = 0
        cx = round((self.x + label_room - xmin) / GRID) * GRID
        cy = round((self.y + 7.62 + ymax) / GRID) * GRID
        self.sheet.add(ref, sym, nets, at=(cx, cy), unit=unit, **kw)
        self.x += w
        self.row_h = max(self.row_h, h)

    def bottom(self):
        return self.y + self.row_h


# ---------------------------------------------------------------------------
# Parts carried over from the imported Rev 1.1 sheets.

BASELINE_COMMIT = "ea7c20b"   # KiCad import of Rev 1.1, with import fixes


def baseline_file(name):
    import subprocess
    return subprocess.run(["git", "show", "%s:hw/kicad/%s" % (BASELINE_COMMIT, name)],
                          capture_output=True, text=True, check=True).stdout


class Baseline:
    """Symbols and properties of the parts of one imported sheet."""

    SKIP_PROPS = {"Reference", "Value", "Footprint", "Datasheet", "Description"}

    def __init__(self, sheet_file):
        import os
        import tempfile
        self.text = baseline_file(sheet_file)
        fd, self.path = tempfile.mkstemp(suffix=".kicad_sch")
        os.write(fd, self.text.encode())
        os.close(fd)
        self.parts = {}
        for m in re.finditer(r'\n\t\(symbol\n', self.text):
            start = m.start() + 2
            blk = self.text[start:_block_end(self.text, start)]
            lib_id = re.search(r'\(lib_id "([^"]+)"\)', blk).group(1)
            props = dict(re.findall(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', blk))
            ref = props.get("Reference", "")
            if ref.startswith("#") or not ref:
                continue
            self.parts[ref] = dict(lib_id=lib_id, props=props)
        self._syms = {}

    def symbol(self, ref):
        lib_id = self.parts[ref]["lib_id"]
        if lib_id not in self._syms:
            self._syms[lib_id] = LibSymbol.from_schematic(self.path, lib_id, lib_id)
        return self._syms[lib_id]

    def place(self, grid, ref, nets, **kw):
        """Re-place a baseline part with new nets, keeping its properties."""
        p = self.parts[ref]["props"]
        fields = {k: v for k, v in p.items() if k not in self.SKIP_PROPS}
        fields.update(kw.pop("fields", {}))
        grid.add(ref, self.symbol(ref), nets, value=kw.pop("value", p.get("Value", "")),
                 footprint=kw.pop("footprint", p.get("Footprint", "")), fields=fields, **kw)
