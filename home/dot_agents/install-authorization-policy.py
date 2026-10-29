#!/usr/bin/env python3
"""Generate additive adapters from the canonical policy; preview by default."""
import argparse, datetime, hashlib, json, os, pathlib, re, shutil, stat, subprocess, tempfile, tomllib

START = '<!-- shared-authorization-policy:start -->'
END = '<!-- shared-authorization-policy:end -->'
TSTART = '# shared-authorization-policy:start'
TEND = '# shared-authorization-policy:end'
JSTART = '// shared-authorization-policy:start'
JEND = '// shared-authorization-policy:end'
PREAMBLE = "# Royal's shared authorization policy (Codex auto-review)\n\nRoyal wrote this policy and installs it himself. Its grants are his standing authorization, given in advance: an action a grant covers needs no repeated approval in the transcript. Its limits, the Launch modes section and project gates still apply, and an action no grant covers gets your normal judgment.\n\n"
GUARD_PATHS = (
    pathlib.Path('/Library/Application Support/ClaudeCode/agent-guard/agent-guard'),
    pathlib.Path(r'C:\Program Files\ClaudeCode\agent-guard\agent-guard.exe'),
    pathlib.Path('/etc/claude-code/agent-guard/agent-guard'),
)
# agent-guard gates Claude Code's PreToolUse, Codex's pre_tool_use hook and, through
# its plugin, OpenCode's tool calls (agent-guard SKILL.md, "Harness coverage"; live
# probes on every host 2026-10-18), so all three follow the guard check (Royal,
# 2026-10-18). Codex counts only where its hooks.json registers the guard, OpenCode
# only where the plugin is installed; elsewhere they get auto.
GUARDED_HARNESSES = ('claude', 'codex', 'opencode')
OPENCODE_GUARD_PLUGIN = pathlib.Path('.config/opencode/plugins/agent-guard.ts')
CODEX_GUARD_HOOKS = pathlib.Path('.codex/hooks.json')
# agent-guard ships as successful main push builds of .github/workflows/agent-guard.yml in
# Fisi-Development/harbor, which the root updater beside each guard installs (skills/agent-guard/
# references/rollout.md, "Automatic rollout"). Each updater run records in state.json the version
# of the newest build it accepts as release_considered; SYSTEM or root writes it, and users read it.
STATE_MAX_AGE = 2*3600  # The updater runs every 15 minutes; an older record is not an answer.
# Hand-written Claude autoMode environment entries Royal retired (2026-10-18): each
# contradicts the policy's grants, and the classifier reads it beside the policy.
RETIRED_ENVIRONMENT = (
    # Says opening MRs and merging need a go; superseded by the 5 Oct widening, the
    # 14 Oct teammate grant and "Autonomous work".
    re.compile(r'^\**Standing authorizations \(AGENTS\.md, 2026-10-01\)'),
)

def read_exact(path):
    with path.open(encoding='utf-8',newline='') as f:
        return f.read()

def updater_state_path(binary):
    return binary.parent.parent/'agent-guard-updater'/'state.json'

def protected(path):
    """Only root may write the record or replace it. On Windows, Program Files already
    keeps it from users, and the updater refuses to run when its directory is not protected."""
    if os.name=='nt': return True
    for item in (path,path.parent):
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022: return False
    return True

def updater_latest(path, fixture=False, now=None):
    """The version the updater last accepted and when it ran, or (None, None) when the record
    is missing, unreadable, stale, from the future, or writable by someone other than root."""
    try:
        if not fixture and not protected(path): return None,None
        state=json.loads(path.read_text(encoding='utf-8'))
        ran=datetime.datetime.fromisoformat(state['last_run'])
        age=((now or datetime.datetime.now(datetime.timezone.utc))-ran).total_seconds()
        match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)',state['release_considered'])
        if match and -300<=age<=STATE_MAX_AGE: return tuple(map(int,match.groups())),state['last_run']
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        pass
    return None,None

def agent_guard_status(guard_bin=None, state_path=None, fixture=False, now=None):
    installed=None
    binary=guard_bin if guard_bin is not None else next((p for p in GUARD_PATHS if p.exists()),None)
    if binary is not None:
        try:
            result=subprocess.run([str(binary),'--version'],capture_output=True,text=True,timeout=10,check=True)
            match=re.fullmatch(r'agent-guard (\d+)\.(\d+)\.(\d+)',result.stdout.strip())
            if match: installed=tuple(map(int,match.groups()))
        except (OSError,subprocess.SubprocessError,UnicodeError):
            pass
    # Read the record of the updater that installs this binary. Without a fresh record the
    # newest build is unknown, so the guard does not count as current.
    if state_path is None and binary is not None: state_path=updater_state_path(pathlib.Path(binary))
    latest,checked=updater_latest(state_path,fixture,now) if state_path is not None else (None,None)
    return {'installed':'.'.join(map(str,installed)) if installed is not None else None,
            'latest':'.'.join(map(str,latest)) if latest is not None else None,
            'updater_checked_at':checked,
            'current':installed is not None and latest is not None and installed>=latest}

def codex_hooked(home):
    """Codex counts as guarded only where its hooks.json runs agent-guard."""
    try: return 'agent-guard' in (home/CODEX_GUARD_HOOKS).read_text(encoding='utf-8')
    except (OSError,UnicodeError): return False

def remove_block(text, start, end):
    if start not in text and end not in text: return text
    if text.count(start)!=1 or text.count(end)!=1 or text.index(start)>=text.index(end):
        raise ValueError('malformed shared policy markers')
    a=text.index(start); b=text.index(end)+len(end)
    if start==JSTART and text[b:b+1]=='\n': b+=1
    if a and text[a-1]=='\n': a-=1
    return text[:a]+text[b:]

def managed(text, start, end, body):
    block=start+'\n'+body.rstrip()+'\n'+end
    if start in text or end in text:
        remove_block(text,start,end)  # Validate before replacement.
        return re.sub(re.escape(start)+r'.*?'+re.escape(end),lambda _:block,text,flags=re.S)
    return text.rstrip()+'\n\n'+block+'\n'

def adopt_orphan_auto_review(text):
    # Codex rewrites config.toml when it saves its own settings and drops the
    # marker comments, leaving our generated table unmanaged. Remove it only
    # when it is plainly ours: the sole key is a policy text, and the rest of
    # the file parses to exactly what it held before.
    before=tomllib.loads(text); table=before.get('auto_review')
    if not (isinstance(table,dict) and set(table)=={'extra_policy'}
            and str(table['extra_policy']).startswith("# Royal's shared authorization policy")):
        return text
    m=re.search(r'^\[auto_review\][ \t]*\r?\n',text,re.M)
    if not m: return text
    want={k:v for k,v in before.items() if k!='auto_review'}
    head=text[:m.start()].rstrip()
    # The table ends at the next header line or at end of file; a '[' line
    # inside the policy string fails the parse check and is skipped.
    ends=[m.end()+x.start() for x in re.finditer(r'^\[',text[m.end():],re.M)]+[len(text)]
    for b in ends:
        tail=text[b:]
        cut=(head+'\n\n'+tail if tail else head+'\n') if head else tail
        try:
            if tomllib.loads(cut)==want: return cut
        except tomllib.TOMLDecodeError:
            pass
    return text

def object_start(text):
    # Skip JSONC leading comments rather than selecting a brace inside one.
    i=0
    while i<len(text):
        if text[i].isspace() or text[i]=='\ufeff': i+=1
        elif text.startswith('//',i):
            j=text.find('\n',i); i=len(text) if j<0 else j+1
        elif text.startswith('/*',i):
            j=text.find('*/',i+2)
            if j<0: raise ValueError('unterminated JSONC comment')
            i=j+2
        else:
            if text[i]!='{': raise ValueError('JSONC object expected')
            return i
    raise ValueError('JSONC object expected')

def atomic_write(path,text,expected):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.policy-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        if path.exists(): shutil.copymode(path,tmp)
        current=read_exact(path) if path.exists() else None
        if current!=expected: raise ValueError(str(path)+': concurrent edit before replacement')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--home',type=pathlib.Path,default=pathlib.Path.home()); p.add_argument('--apply',action='store_true')
    p.add_argument('--guard-bin',type=pathlib.Path); p.add_argument('--updater-state',type=pathlib.Path); args=p.parse_args()
    # The overrides exist for fixture homes; on the real home they could fake a current guard.
    if (args.guard_bin or args.updater_state) and args.home.resolve()==pathlib.Path.home().resolve():
        p.error('--guard-bin and --updater-state are only for a fixture --home')
    home=args.home.resolve(); policy=home/'.agents/authorization-policy.md'; content=policy.read_text(encoding='utf-8'); digest=hashlib.sha256(content.encode()).hexdigest()
    # Instruction files are chezmoi snapshots shared by every host, so they name
    # the policy by a home-relative path; an absolute one drifts per host.
    shared='~/.agents/authorization-policy.md'
    statepath=home/'.agents/authorization-adapter-state.json'
    nobackup=set()  # Files holding credentials get no plaintext backup copy.
    state=json.loads(statepath.read_text(encoding='utf-8')) if statepath.exists() else {}; nextstate={}; planned={}
    def put(path,text):
        path=path.resolve(); old=read_exact(path) if path.exists() else None
        if path in planned and planned[path][1]!=text: raise ValueError('conflicting symlink targets')
        if old!=text: planned[path]=(old,text)
    def instruction(path,body):
        old=path.read_text(encoding='utf-8') if path.exists() else ''
        put(path,managed(old,START,END,body))
    guard=agent_guard_status(args.guard_bin,args.updater_state,fixture=home!=pathlib.Path.home().resolve())
    mode='full-access' if guard['current'] else 'auto'
    telepathica={'path':None,'before':None,'after':None}
    for path in (home/'.telepathica/config.json',home/'.agent-mailbox/config.json'):
        if not path.exists(): continue
        old=read_exact(path)
        try: d=json.loads(old)
        except ValueError as e: raise ValueError(str(path)+': not valid JSON ('+e.__class__.__name__+')') from None
        before=d.get('t3_runtime_modes') if isinstance(d,dict) else None
        if not isinstance(d,dict) or not isinstance(before,(dict,type(None))):
            raise ValueError(str(path)+': reconcile a non-object config or t3_runtime_modes first')
        modes=d.setdefault('t3_runtime_modes',{})
        before=dict(before) if before is not None else None
        for harness in GUARDED_HARNESSES:
            plugged={'opencode':lambda:(home/OPENCODE_GUARD_PLUGIN).exists(),
                     'codex':lambda:codex_hooked(home)}.get(harness,lambda:True)()
            modes[harness]=mode if plugged else 'auto'
        generated=json.dumps(d,indent=2)
        if '\r\n' in old: generated=generated.replace('\n','\r\n')
        put(path,generated); nobackup.add(path.resolve())
        telepathica={'path':str(path),'before':before,'after':dict(modes)}
        break
    for name in ('.codex','.codex-work'):
        root=home/name; path=root/'config.toml'
        if not path.exists(): continue
        old=path.read_text(encoding='utf-8')
        if old.count(TSTART)==1 and TEND not in old:
            # Codex kept the start comment above [auto_review] and dropped the
            # end comment; drop the dangling start and adopt the table below.
            old=re.sub(r'^'+re.escape(TSTART)+r'[ \t]*\r?\n','',old,count=1,flags=re.M)
        stripped=remove_block(old,TSTART,TEND)
        if TSTART not in old:
            stripped=adopt_orphan_auto_review(stripped)
        if 'auto_review' in tomllib.loads(stripped):
            raise ValueError(str(path)+': reconcile unmanaged auto_review first')
        block='[auto_review]\nextra_policy = '+json.dumps(PREAMBLE+content,ensure_ascii=False)
        generated=managed(old if TSTART in old else stripped,TSTART,TEND,block)
        tomllib.loads(generated)
        put(path,generated)
        instruction(root/'AGENTS.md','Read '+shared+' before provider delegation or remote writes; apply it alongside project gates.')
    def section(title):
        if '## '+title+'\n\n' not in content: raise ValueError(str(policy)+': policy lacks section '+title+'; apply the matching policy first')
        return content.split('## '+title+'\n\n',1)[1].split('\n## ',1)[0].strip()
    # Claude's classifier reads allow entries as exceptions to its block rules;
    # each grant that should lift a default block goes here.
    allow='\n\n'.join(section(t) for t in ('Autonomous work','Authorized company GLM review',"Royal's GitHub repositories",'Telepathica commands','Chezmoi rollout','Launch modes'))
    # One Claude home per host since 2026-10-13 (the Mac's ~/.claude-personal was
    # merged into ~/.claude), so a stray recreated personal home is left alone.
    for name in ('.claude',):
        root=home/name
        if not root.exists(): continue
        path=root/'settings.json'; d=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}; auto=d.setdefault('autoMode',{})
        saved=state.get(str(path.resolve()),{}); generated={}
        for key,entry in [('environment','[shared-authorization-policy] '+content),('allow','[shared-authorization-policy] '+allow)]:
            values=auto.get(key,['$defaults'])
            if not isinstance(values,list) or any(not isinstance(v,str) for v in values): raise ValueError('autoMode string list expected')
            if '$defaults' not in values: raise ValueError(str(path)+': reconcile custom '+key+' without $defaults first')
            previous=saved.get(key)
            if previous is not None: values=[v for v in values if v!=previous]
            if key=='environment': values=[v for v in values if not any(r.match(v) for r in RETIRED_ENVIRONMENT)]
            if any(v.startswith('[shared-authorization-policy]') and v!=entry for v in values): raise ValueError('untracked generated Claude entry')
            if entry not in values: values.append(entry)
            auto[key]=values; generated[key]=entry
        nextstate[str(path.resolve())]=generated
        put(path,json.dumps(d,indent=2,ensure_ascii=False)+'\n')
        instruction(root/'CLAUDE.md','@'+shared)
    oc=home/'.config/opencode'
    if oc.exists():
        path=oc/'opencode.jsonc' if (oc/'opencode.jsonc').exists() else oc/'opencode.json'
        old=path.read_text(encoding='utf-8') if path.exists() else '{}\n'; clean=remove_block(old,JSTART,JEND)
        urls=('https://openrouter.ai/api/*','https://api.fireworks.ai/inference/*')
        if path.suffix=='.jsonc':
            basefile=oc/'opencode.json'
            base=json.loads(basefile.read_text(encoding='utf-8')) if basefile.exists() else {}
            if 'permission' in base or 'permissions' in base: raise ValueError('reconcile earlier JSON permission layer before generating JSONC permissions')
            if re.search(r'"(?:instructions|permission|permissions)"\s*:',clean): raise ValueError(str(path)+': reconcile existing JSONC instructions/permission first')
            pos=object_start(clean)
            fragment=json.dumps({'instructions':[policy.as_posix()],'permission':{'webfetch':dict.fromkeys(urls,'ask')}},indent=2)[1:-1].strip()
            # Preserve exactly the whitespace outside our block.
            insertion='\n'+JSTART+'\n'+fragment+',\n'+JEND+'\n'
            put(path,clean[:pos+1]+insertion+clean[pos+1:])
        else:
            d=json.loads(old); existing=d.setdefault('instructions',[])
            if policy.as_posix() not in existing: existing.append(policy.as_posix())
            perm=d.setdefault('permission',{}); web=perm.setdefault('webfetch',{})
            if not isinstance(web,dict): raise ValueError('reconcile scalar webfetch permission first')
            for url in urls: web.setdefault(url,'ask')  # Preserve existing deny/ask/allow.
            put(path,json.dumps(d,indent=2,ensure_ascii=False)+'\n')
    put(statepath,json.dumps(nextstate,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'policy_sha256':digest,'apply':args.apply,'changed_paths':[str(x) for x in planned],
                      'agent_guard':guard,'launch_mode':mode,'guarded_harnesses':list(GUARDED_HARNESSES),'telepathica':telepathica}))
    if args.apply:
        # Reject concurrent edits before writing any file. Each replacement is atomic;
        # the multi-file update is not a transaction. Rerun to finish interrupted installs.
        for path,(old,new) in planned.items():
            current=read_exact(path) if path.exists() else None
            if current!=old: raise ValueError(str(path)+': changed since preview')
        for path,(old,new) in planned.items():
            if path.exists() and path not in nobackup:
                backup=path.with_name(path.name+'.before-shared-authorization')
                if not backup.exists(): shutil.copy2(path,backup)
            atomic_write(path,new,old)

if __name__=='__main__': main()
