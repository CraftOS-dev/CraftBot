"""Port allocator + instance registry acceptance (app.agent_app.instances).

Run:  python3 -m app.agent_app.test_instances

Style follows test_data_safety.py: a module-level assert script, no pytest.
The headline case is the 2026-09-10 deadlock — a browser probe stamped the
wrong project because two projects held records claiming the same port. Under
the registry that is structurally impossible: ports are unique among active
instances and identity is the instance id, so §5 reproduces the exact scenario
and proves the stamp lands on the right instance.
"""

import tempfile
from pathlib import Path

from app.agent_app.instances import (
    LIVE_RANGE,
    ROLE_LIVE,
    ROLE_SHADOW,
    SHADOW_RANGE,
    Instance,
    InstanceRegistry,
    PortAllocator,
    PortPoolExhausted,
)


def _reg(tmp):
    return InstanceRegistry(Path(tmp) / "agent_app_instances.json", PortAllocator())


# ── §1 allocator: reserve-before-return, ranges, release, exhaustion ───────
with tempfile.TemporaryDirectory() as tmp:
    alloc = PortAllocator()
    a = alloc.reserve(ROLE_SHADOW)
    b = alloc.reserve(ROLE_SHADOW)
    assert a != b, "two reserves must never hand out the same port"
    assert SHADOW_RANGE[0] <= a <= SHADOW_RANGE[1]
    assert alloc.is_reserved(a) and alloc.is_reserved(b)
    live = alloc.reserve(ROLE_LIVE)
    assert LIVE_RANGE[0] <= live <= LIVE_RANGE[1]
    # release re-hands the lowest freed port
    alloc.release(a)
    assert not alloc.is_reserved(a)
    c = alloc.reserve(ROLE_SHADOW)
    assert c == a, "the released port is the lowest free one and comes back first"
    # reserve_known is idempotent and marks a decided (sticky live) port
    alloc.reserve_known(3177)
    assert alloc.is_reserved(3177)
    alloc.reserve_known(3177)
    # exhaustion raises a typed error, never a silent wrap. Reserve until it
    # raises (some live ports may already be bound by real apps on this
    # machine, so the count is not assumed to be the full range width).
    small = PortAllocator()
    span = LIVE_RANGE[1] - LIVE_RANGE[0] + 1
    reserved = 0
    raised = False
    try:
        for _ in range(span + 1):
            small.reserve(ROLE_LIVE)
            reserved += 1
    except PortPoolExhausted as e:
        assert e.role == ROLE_LIVE
        raised = True
    assert raised, "exhausted pool must raise"
    assert reserved <= span
print("§1 allocator: reserve/release/ranges/exhaustion: OK")


# ── §2 shadow instances: unique ports, eviction, one-per-project ───────────
with tempfile.TemporaryDirectory() as tmp:
    reg = _reg(tmp)
    a = reg.create_shadow("projA", token="t", boot_id="b1", dir="/x/a")
    b = reg.create_shadow("projB", token="t", boot_id="b2", dir="/x/b")
    assert a.port != b.port
    assert a.instance_id != b.instance_id
    assert reg.shadow("projA").instance_id == a.instance_id
    # re-create for the same project evicts the old one and frees its port
    old_port = a.port
    a2 = reg.create_shadow("projA", token="t", boot_id="b3", dir="/x/a2")
    assert reg.shadow("projA").instance_id == a2.instance_id
    assert reg.get(a.instance_id) is None, "the previous shadow is gone"
    assert len([i for i in reg.all() if i.project_id == "projA"]) == 1
    # the freed port is available again (lowest-free, so a2 may reuse it)
    assert a2.port == old_port or not reg._ports.is_reserved(old_port)
print("§2 shadow instances: unique ports + one-per-project eviction: OK")


# ── §3 live is sticky: registered, removable, port retained ────────────────
with tempfile.TemporaryDirectory() as tmp:
    reg = _reg(tmp)
    lv = reg.register_live("projA", 3100, pid=4242, token="t")
    assert reg.live("projA").pid == 4242
    assert reg._ports.is_reserved(3100)
    # removing the live instance keeps the sticky port reserved
    reg.remove(lv.instance_id)
    assert reg.live("projA") is None
    assert reg._ports.is_reserved(3100), "live port stays reserved across stop"
    # a shadow removal DOES release its port
    sh = reg.create_shadow("projA", token="t", boot_id="b", dir="/x")
    sp = sh.port
    reg.remove(sh.instance_id)
    assert not reg._ports.is_reserved(sp), "shadow port released on removal"
print("§3 live sticky vs shadow ephemeral port lifetimes: OK")


# ── §4 route + persistence + clear/reset ───────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "agent_app_instances.json"
    reg = InstanceRegistry(path, PortAllocator())
    reg.register_live("projA", 3100, pid=1, token="t")
    reg.create_shadow("projA", token="t", boot_id="b", dir="/x")
    # route prefers the shadow while one is up
    assert reg.route("projA").role == ROLE_SHADOW
    # persistence round-trips through the file
    reg2 = InstanceRegistry(path, PortAllocator())
    assert reg2.live("projA") is not None and reg2.shadow("projA") is not None
    # clear_project removes all instances for a project
    removed = reg.clear_project("projA")
    assert len(removed) == 2 and reg.route("projA") is None
    # reset snapshots then empties, releasing shadow ports
    reg.register_live("projB", 3101, pid=2, token="t")
    reg.create_shadow("projB", token="t", boot_id="b", dir="/x")
    prior = reg.reset()
    assert len(prior) == 2 and reg.all() == []
print("§4 route + persistence + clear/reset: OK")


# ── §5 THE regression: a recycled port belongs to exactly the new owner ────
# projA's shadow takes a shadow port, then is torn down (promote). projB's
# shadow reuses that exact port. The registry resolves the port to projB, and
# projA's instance is gone — the old deadlock matched a stale record that
# shared the port and acted on the wrong project.
with tempfile.TemporaryDirectory() as tmp:
    reg = _reg(tmp)
    a = reg.create_shadow("projA", token="t", boot_id="ba", dir="/x/a")
    recycled = a.port
    reg.remove(a.instance_id)  # promote tore projA's shadow down
    b = reg.create_shadow("projB", token="t", boot_id="bb", dir="/x/b")
    assert b.port == recycled, "lowest-free means projB reuses projA's old port"
    assert reg.get(a.instance_id) is None, "the dead projA instance is gone"
    assert reg.shadow("projA") is None
    assert reg.shadow("projB").instance_id == b.instance_id
    assert reg.shadow("projB").port == recycled, "the port belongs to projB only"
print("§5 recycled port belongs to exactly the new owner (deadlock fix): OK")


# ── §6 Instance value semantics ────────────────────────────────────────────
inst = Instance(
    instance_id="shadow-x-1",
    project_id="x",
    role=ROLE_SHADOW,
    port=3900,
    dir="/boot",
)
assert inst.url == "http://127.0.0.1:3900"
assert inst.data_dir == Path("/boot") / "pb_data"
assert inst.log_dir == Path("/boot") / "logs"
assert Instance.from_dict(inst.to_dict()).instance_id == "shadow-x-1"
print("§6 Instance url/data_dir/log_dir/round-trip: OK")


print("\nInstances acceptance: ALL GREEN")
