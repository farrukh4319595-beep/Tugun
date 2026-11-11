#!/usr/bin/env python3
"""Role tests against the migrated seed data. Each check runs in its own session as a given login,
exactly as the API would (role 'authenticated' + JWT sub)."""
import hashlib, json, subprocess, sys, time, uuid

PSQL = ["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-U", "tugun_owner", "-d", "tugun"]
NS = uuid.UUID("6f6b1b62-6b8e-4c39-9a51-7475676e0001")
U = lambda kind, legacy: str(uuid.uuid5(NS, f"baraka-les:{kind}:{legacy}"))
ORG = U("org", "")
seed = json.load(open("../legacy/seed.json"))
# Test-only: recover the demo PINs so the kiosk can be exercised (the real migration does this inside SQL).
salt = seed["secure/pins"]["salt"]
PIN = {}
for k, h in seed["secure/pins"]["pins"].items():
    PIN[k] = next(p for p in (f"{n:04d}" for n in range(10000)) if hashlib.sha256(f"{salt}:{p}".encode()).hexdigest() == h)

def sql(stmts, user=None, role="authenticated"):
    cmd = list(PSQL)
    if user is not None or role == "anon":
        cmd += ["-c", f"set role {role}"]
        if user: cmd += ["-c", f"set request.jwt.claim.sub = '{user}'"]
    for s in ([stmts] if isinstance(stmts, str) else stmts):
        cmd += ["-c", s]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, p.stdout.strip(), p.stderr.strip()

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  → {detail}"))

def val(stmts, user=None, role="authenticated"):
    ok, out, err = sql(stmts, user, role)
    if not ok: raise RuntimeError(err)
    return out.splitlines()[-1] if out else ""

def expect(name, user, stmt, want, role="authenticated"):
    ok, out, err = sql(stmt, user, role)
    got = out.splitlines()[-1] if out else ""
    check(name, ok and got == str(want), err or f"got {got!r}, want {want!r}")

def deny(name, user, stmt, role="authenticated"):
    ok, out, err = sql(stmt, user, role)
    check(name, not ok, f"unexpectedly succeeded: {out!r}")
    return err

# ─────────── fixtures (as owner) ───────────
R, HEAD, XOD, OTH, GUEST, TERM, NOBODY, R2 = (str(uuid.uuid4()) for _ in range(8))
S = lambda legacy: U("staff", legacy)
D = lambda legacy: U("dept", legacy)
T = lambda legacy: U("task", legacy)
ORG2 = str(uuid.uuid4()); B2, D2, S2, T2 = (str(uuid.uuid4()) for _ in range(4))
ok, _, err = sql([
    f"insert into auth.users (id) values ('{R}'),('{HEAD}'),('{XOD}'),('{OTH}'),('{GUEST}'),('{TERM}'),('{NOBODY}'),('{R2}')",
    f"""insert into public.members (user_id, org_id, role, staff_id) values
        ('{R}','{ORG}','rahbar',null), ('{HEAD}','{ORG}','xodim','{S('b2b-sales-1')}'),
        ('{XOD}','{ORG}','xodim','{S('b2b-sales-2')}'), ('{OTH}','{ORG}','xodim','{S('b2c-sales-2')}'),
        ('{GUEST}','{ORG}','mehmon',null), ('{TERM}','{ORG}','terminal',null)""",
    # a second company in the same database
    f"insert into public.orgs (id, name) values ('{ORG2}', 'Boshqa kompaniya')",
    f"insert into public.branches (id, org_id, name) values ('{B2}','{ORG2}','X')",
    f"insert into public.departments (id, org_id, branch_id, name) values ('{D2}','{ORG2}','{B2}','Savdo')",
    f"insert into public.staff (id, org_id, dept_id, full_name) values ('{S2}','{ORG2}','{D2}','Begona xodim')",
    f"insert into public.tasks (id, org_id, title, owner_staff_id) values ('{T2}','{ORG2}','Begona task','{S2}')",
    f"insert into public.members (user_id, org_id, role) values ('{R2}','{ORG2}','rahbar')",
])
if not ok: sys.exit(err)

# a task where b2b-sales-2 is an assignee but neither owner nor creator
ASG = val(f"""select t.id from public.tasks t join public.task_staff ts on ts.task_id = t.id
              where ts.staff_id = '{S('b2b-sales-2')}' and t.owner_staff_id <> '{S('b2b-sales-2')}'
                and t.created_by is distinct from '{S('b2b-sales-2')}' limit 1""")
NOT_ASG = val(f"""select t.id from public.tasks t where org_id = '{ORG}' and not exists
              (select 1 from public.task_staff ts where ts.task_id = t.id and ts.staff_id = '{S('b2b-sales-2')}')
              and t.owner_staff_id <> '{S('b2b-sales-2')}' limit 1""")
OTHER_DEPT_TASK = val(f"""select t.id from public.tasks t join public.staff o on o.id = t.owner_staff_id
              where t.org_id = '{ORG}' and o.dept_id <> '{D('b2b-sales')}' and not exists
              (select 1 from public.task_depts td where td.task_id = t.id and td.dept_id = '{D('b2b-sales')}') limit 1""")
TOTAL_ATT = val(f"select count(*) from public.attendance where org_id = '{ORG}'")
DEPT_ATT = val(f"select count(*) from public.attendance a join public.staff s on s.id = a.staff_id where s.dept_id = '{D('b2b-sales')}'")
OWN_ATT = val(f"select count(*) from public.attendance where staff_id = '{S('b2b-sales-2')}'")

print(f"\nfixtures: assignee task {ASG[:8]}, attendance org/dept/own = {TOTAL_ATT}/{DEPT_ATT}/{OWN_ATT}\n")

# ─────────── 1. who can read what ───────────
expect("anon sees no tasks", None, "select count(*) from public.tasks", 0, role="anon")
expect("non-member sees no tasks", NOBODY, "select count(*) from public.tasks", 0)
expect("rahbar sees all 9 tasks of own org only", R, "select count(*) from public.tasks", 9)
expect("rahbar sees 27 staff", R, "select count(*) from public.staff", 27)
expect("other org's rahbar sees none of ours", R2, f"select count(*) from public.tasks where org_id = '{ORG}'", 0)
expect("guest sees tasks (read-only role)", GUEST, "select count(*) from public.tasks", 9)
expect("terminal sees no tasks", TERM, "select count(*) from public.tasks", 0)
expect("terminal sees no staff list", TERM, "select count(*) from public.staff", 0)
expect("rahbar sees all attendance", R, "select count(*) from public.attendance", TOTAL_ATT)
expect("boshliq sees own department attendance", HEAD, "select count(*) from public.attendance", DEPT_ATT)
expect("xodim sees only own attendance", XOD, "select count(*) from public.attendance", OWN_ATT)
expect("guest sees no attendance", GUEST, "select count(*) from public.attendance", 0)
deny("nobody reads PIN table", R, "select count(*) from private.staff_pins")
deny("nobody reads org secret", R, "select pepper from private.org_secrets")
expect("my_context: boshliq", HEAD, "select public.my_context()->>'role'", "boshliq")
expect("my_context: xodim", XOD, "select public.my_context()->>'role'", "xodim")
expect("my_context: rahbar", R, "select public.my_context()->>'role'", "rahbar")

# ─────────── 2. structure is rahbar-only ───────────
expect("rahbar renames a department", R, f"update public.departments set name = name where id = '{D('b2b-sales')}' returning 1", 1)
expect("boshliq cannot rename a department (0 rows)", HEAD, f"with u as (update public.departments set name = 'X' where id = '{D('b2b-sales')}' returning 1) select count(*) from u", 0)
deny("boshliq cannot add staff", HEAD, f"insert into public.staff (org_id, dept_id, full_name) values ('{ORG}', '{D('b2b-sales')}', 'Yangi')")
expect("xodim cannot make himself admin (0 rows)", XOD, f"with u as (update public.staff set is_admin = true where id = '{S('b2b-sales-2')}' returning 1) select count(*) from u", 0)
deny("xodim cannot grant himself rahbar account", XOD, f"insert into public.members (user_id, org_id, role) values ('{NOBODY}', '{ORG}', 'rahbar')")
expect("xodim cannot change own account role (0 rows)", XOD, f"with u as (update public.members set role = 'rahbar' where user_id = '{XOD}' returning 1) select count(*) from u", 0)
deny("rahbar cannot remove own rahbar role", R, f"update public.members set role = 'xodim' where user_id = '{R}'")
deny("rahbar cannot attach staff from another org", R, f"update public.departments set head_staff_id = '{S2}' where id = '{D('b2b-sales')}'")

# ─────────── 3. tasks ───────────
deny("xodim cannot create a task", XOD, f"insert into public.tasks (org_id, title, owner_staff_id) values ('{ORG}', 'X', '{S('b2b-sales-2')}')")
deny("guest cannot create a task", GUEST, f"insert into public.tasks (org_id, title, owner_staff_id) values ('{ORG}', 'X', '{S('b2b-sales-2')}')")
NEW = val(f"insert into public.tasks (org_id, title, owner_staff_id, due_date) values ('{ORG}', 'Boshliq taski', '{S('b2b-sales-2')}', current_date + 3) returning id", HEAD)
check("boshliq creates a task", bool(NEW))
expect("creator is stamped by the server", R, f"select created_by = '{S('b2b-sales-1')}' from public.tasks where id = '{NEW}'", "t")
expect("boshliq attaches own department to new task", HEAD, f"insert into public.task_depts (task_id, dept_id) values ('{NEW}', '{D('b2b-sales')}') returning 1", 1)
expect("boshliq adds an assignee", HEAD, f"insert into public.task_staff (task_id, staff_id) values ('{NEW}', '{S('b2b-sales-3')}') returning 1", 1)
expect("assignee is notified", R, f"select count(*) from public.activity where task_id = '{NEW}' and kind = 'assign' and '{S('b2b-sales-3')}' = any(to_staff)", 1)
deny("cannot assign a person from another org", R, f"insert into public.task_staff (task_id, staff_id) values ('{NEW}', '{S2}')")
deny("other org's rahbar cannot add our staff to their task", R2, f"insert into public.task_staff (task_id, staff_id) values ('{T2}', '{S('b2b-sales-1')}')")
expect("other org's rahbar cannot edit our task (0 rows)", R2, f"with u as (update public.tasks set title = 'hack' where id = '{NEW}' returning 1) select count(*) from u", 0)

deny("assignee cannot rename a task", XOD, f"update public.tasks set title = 'boshqa' where id = '{ASG}'")
deny("assignee cannot change the mas'ul", XOD, f"update public.tasks set owner_staff_id = '{S('b2b-sales-2')}' where id = '{ASG}'")
expect("assignee moves progress", XOD, f"update public.tasks set progress = 70 where id = '{ASG}' returning progress", 70)
expect("assignee moves status", XOD, f"update public.tasks set status = 'review' where id = '{ASG}' returning status", "review")
expect("status change is logged with actor", R, f"select count(*) from public.task_events where task_id = '{ASG}' and kind = 'status' and actor_staff = '{S('b2b-sales-2')}'", 1)
expect("status change notifies mas'ul", R, f"select count(*) from public.activity a join public.tasks t on t.id = a.task_id where a.task_id = '{ASG}' and a.kind = 'status' and t.owner_staff_id = any(a.to_staff)", 1)
expect("done sets done_at and 100%", XOD, f"update public.tasks set status = 'done' where id = '{ASG}' returning progress = 100 and done_at is not null", "t")
expect("xodim cannot touch a task he is not on (0 rows)", XOD, f"with u as (update public.tasks set progress = 1 where id = '{NOT_ASG}' returning 1) select count(*) from u", 0)
expect("boshliq cannot delete a task owned by another department (0 rows)", HEAD, f"with d as (delete from public.tasks where id = '{OTHER_DEPT_TASK}' returning 1) select count(*) from d", 0)
deny("nobody writes task history directly", R, f"insert into public.task_events (org_id, task_id, kind) values ('{ORG}', '{NEW}', 'fake')")
expect("boshliq deletes own department's task", HEAD, f"with d as (delete from public.tasks where id = '{NEW}' returning 1) select count(*) from d", 1)

# ─────────── 4. comments ───────────
expect("assignee comments as himself", XOD, f"insert into public.task_comments (task_id, staff_id, user_id, body) values ('{ASG}', '{S('b2b-sales-2')}', '{XOD}', 'Tayyor') returning 1", 1)
expect("comment bumps last_comment_at", R, f"select last_comment_at > now() - interval '1 minute' from public.tasks where id = '{ASG}'", "t")
deny("cannot comment in someone else's name", XOD, f"insert into public.task_comments (task_id, staff_id, user_id, body) values ('{ASG}', '{S('b2b-sales-1')}', '{XOD}', 'soxta')")
deny("guest cannot comment", GUEST, f"insert into public.task_comments (task_id, staff_id, user_id, body) values ('{ASG}', null, '{GUEST}', 'salom')")
deny("other org cannot comment on our task", R2, f"insert into public.task_comments (task_id, staff_id, user_id, body) values ('{ASG}', null, '{R2}', 'salom')")

# ─────────── 5. attendance ───────────
deny("even rahbar cannot write attendance directly", R, f"insert into public.attendance (org_id, staff_id, day, in_time) values ('{ORG}', '{S('b2b-sales-2')}', '2026-10-01', '09:00')")
expect("boshliq corrects own department with a reason", HEAD, f"select public.attendance_set('{S('b2b-sales-2')}', '2026-11-03', '09:00', '18:00', 'Terminal ishlamadi')", "")
expect("correction is in the audit log", R, f"select count(*) from public.attendance_edits where staff_id = '{S('b2b-sales-2')}' and day = '2026-11-03' and actor_staff = '{S('b2b-sales-1')}' and prev is not null", 1)
deny("boshliq cannot correct another department", HEAD, f"select public.attendance_set('{S('b2c-sales-2')}', '2026-11-03', '09:00', '18:00', 'sabab bor')")
deny("xodim cannot correct own attendance", XOD, f"select public.attendance_set('{S('b2b-sales-2')}', '2026-11-04', '08:00', '18:00', 'sabab bor')")
deny("correction needs a reason", R, f"select public.attendance_set('{S('b2b-sales-2')}', '2026-11-04', '08:00', '18:00', '')")

# ─────────── 6. PIN terminal ───────────
p_x, p_head = PIN["b2b-sales-2"], PIN["b2b-sales-1"]
deny("xodim cannot set PINs", XOD, f"select public.set_pin('{S('b2b-sales-2')}', '9999')")
deny("PIN must be unique", R, f"select public.set_pin('{S('b2b-sales-3')}', '{p_x}')")
deny("PIN must have the org's length", R, f"select public.set_pin('{S('b2b-sales-3')}', '12')")
deny("xodim account cannot use the kiosk", XOD, f"select public.kiosk_punch('{p_x}')")
expect("migrated PIN works: check-in", TERM, f"select public.kiosk_punch('{p_x}')->>'kind'", "in")
expect("second punch within 2 minutes is ignored", TERM, f"select public.kiosk_punch('{p_x}')->>'kind'", "already_in")
expect("punch creates a raw event", R, f"select count(*) from public.attendance_marks where staff_id = '{S('b2b-sales-2')}' and source = 'kiosk'", 1)
for i in range(5): sql(f"select public.kiosk_punch('0000x')", TERM)
expect("5 wrong PINs lock the terminal", TERM, f"select public.kiosk_punch('{p_x}')->>'error'", "locked")
sql("delete from private.kiosk_attempts")
expect("kiosk exit with department head PIN", TERM, f"select public.kiosk_exit('{p_head}')", "t")
expect("kiosk exit refused with ordinary PIN", TERM, f"select public.kiosk_exit('{p_x}')", "f")
deny("terminal cannot edit attendance", TERM, f"select public.attendance_set('{S('b2b-sales-2')}', '2026-11-05', '09:00', '18:00', 'sabab bor')")

# ─────────── 7. charter & "Tanishdim" ───────────
v0 = val(f"select version from public.charter where org_id = '{ORG}'")
expect("xodim acknowledges current charter", XOD, f"select public.acknowledge('charter', '{ORG}')->>'version'", v0)
deny("nobody inserts acknowledgements directly", XOD, f"insert into public.acknowledgements (org_id, staff_id, kind, version) values ('{ORG}', '{S('b2b-sales-1')}', 'charter', 99)")
deny("guest cannot acknowledge", GUEST, f"select public.acknowledge('charter', '{ORG}')")
expect("rahbar edits a section → charter version +1", R, [f"update public.charter_sections set body = body || ' ' where org_id = '{ORG}' and legacy_id = 's1'", f"select version from public.charter where org_id = '{ORG}'"], int(v0) + 1)
expect("old acknowledgement no longer counts", R, f"select count(*) from public.acknowledgements a join public.charter c on c.org_id = a.org_id where a.staff_id = '{S('b2b-sales-2')}' and a.kind = 'charter' and a.version = c.version", 0)
pv = val(f"select p.version from public.positions p join public.staff s on s.position_id = p.id where s.id = '{S('b2b-sales-2')}'")
expect("editing duties bumps the position version", R, f"update public.positions p set duties = duties || 'Yangi vazifa'::text from public.staff s where s.position_id = p.id and s.id = '{S('b2b-sales-2')}' returning p.version", int(pv) + 1)
expect("acknowledge own position at new version", XOD, f"select public.acknowledge('position', '{ORG}')->>'version'", int(pv) + 1)
expect("xodim sees only own acknowledgements", XOD, "select count(distinct staff_id) from public.acknowledgements", 1)

# ─────────── 8. notifications ───────────
total_act = val(f"select count(*) from public.activity where org_id = '{ORG}'")
mine = val(f"select count(*) from public.activity where org_id = '{ORG}' and (actor_staff = '{S('b2b-sales-2')}' or '{S('b2b-sales-2')}' = any(to_staff))")
expect("xodim sees only activity addressed to him", XOD, "select count(*) from public.activity", mine)
check("…which is less than the whole feed", int(mine) < int(total_act), f"{mine} vs {total_act}")

# ─────────── 9. scale: 100 staff, 3 000 tasks, 1 year of attendance ───────────
sql([f"""insert into public.staff (org_id, dept_id, full_name)
         select '{ORG}', '{D('b2c-sales')}', 'Sinov ' || g from generate_series(1, 73) g""",
     f"""insert into public.tasks (org_id, title, owner_staff_id, status, due_date)
         select '{ORG}', 'Yuklama ' || g, (select id from public.staff where org_id = '{ORG}' order by random() limit 1),
                (array['new','progress','review','done']::app.task_status[])[1 + g % 4], current_date + (g % 60) - 30
         from generate_series(1, 3000) g""",
     f"""insert into public.task_staff (task_id, staff_id, org_id)
         select t.id, s.id, t.org_id from public.tasks t cross join lateral
           (select id from public.staff where org_id = t.org_id and id <> t.owner_staff_id order by md5(t.id::text || id::text) limit 3) s
         where t.title like 'Yuklama %' """,
     f"""insert into public.attendance (org_id, staff_id, day, in_time, out_time)
         select '{ORG}', s.id, d::date, '09:00', '18:00' from public.staff s,
                generate_series(current_date - 365, current_date - 30, interval '1 day') d
         where s.org_id = '{ORG}' and extract(isodow from d) < 6 on conflict do nothing""",
     "analyze"])
for name, user, q_, limit in [
    ("rahbar: all open tasks with assignees", R, "select count(*) from (select t.id, array_agg(ts.staff_id) from public.tasks t left join public.task_staff ts on ts.task_id = t.id where t.status <> 'done' group by t.id) x", 100),
    ("xodim: my tasks", XOD, f"select count(*) from public.tasks t where exists (select 1 from public.task_staff ts where ts.task_id = t.id and ts.staff_id = '{S('b2b-sales-2')}')", 100),
    ("boshliq: this month's attendance", HEAD, "select count(*) from public.attendance where day >= date_trunc('month', current_date - 60)", 100),
    ("rahbar: month attendance report", R, "select count(*) from public.attendance where day >= current_date - 60", 300)]:
    ok, out, err = sql("explain (analyze, format json) " + q_, user)
    ms = json.loads(out)[0]["Execution Time"] if ok else -1
    check(f"speed · {name}: {ms:.1f} ms on server (limit {limit})", ok and 0 <= ms < limit, err or f"{ms:.1f} ms")

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
