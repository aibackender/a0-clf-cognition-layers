from __future__ import annotations
from dataclasses import dataclass, field
from datetime import timedelta
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlparse
import posixpath, re, shlex
import json
from usr.plugins.cognition_layers.clf.types import AgentContext, ToolInvocation, VerificationCacheEntry, VerificationResult, stable_hash, utc_now_iso
from usr.plugins.cognition_layers.helpers import state
from usr.plugins.cognition_layers.helpers.policy import get_in, layer_mode, scope_for_agent, verification_cache_hash

_URL_RE=re.compile(r"https?://[^\s'\"]+")
_SECRET_RE=re.compile(r"(api[_-]?key|token|password|secret|authorization|bearer|client[_-]?secret)", re.I)
_LONG_SECRET_RE=re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{28,}(?![A-Za-z0-9])")
_UUID_RE=re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
_SLUG_TOKEN_RE=re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+){2,}$")
_HEREDOC_RE=re.compile(r"<<-?\s*['\"]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)['\"]?")
_SHELLS={"sh","bash","zsh","dash","ksh"}; _DOWNLOADERS={"curl","wget","fetch"}; _SHELL_TOOLS={"code_execution_tool","terminal","shell","bash","sh","python_execution_tool"}; _SHELL_ARG_KEYS={"command","cmd","shell","bash","sh","script","stdin"}; _SHELL_TEXT_ONLY_KEYS={"content","text","payload","body","message","description","summary","reason","notes","comment","title","caption"}
_VERIFICATION_CACHE_KEY_VERSION="2"

def _norm(name:str)->str: return (name or "").strip().lower().replace(" ","_")
def _collapse(text:str)->str: return " ".join((text or "").lower().split())
def _tool_aliases(name:str)->list[str]:
    normalized=_norm(name)
    if not normalized: return []
    aliases={normalized}
    for sep in (":","/"):
        if sep in normalized:
            aliases.add(normalized.split(sep,1)[0])
    if normalized.endswith("_tool"): aliases.add(normalized[:-5])
    return [alias for alias in aliases if alias]
def _strings(value:Any, include_keys:bool=False)->list[str]:
    out=[]
    if value is None: return out
    if isinstance(value,str): out.append(value)
    elif isinstance(value,dict):
        for k,v in value.items():
            if include_keys: out.extend(_strings(k, include_keys))
            out.extend(_strings(v, include_keys))
    elif isinstance(value,(list,tuple,set)):
        for i in value: out.extend(_strings(i, include_keys))
    else: out.append(str(value))
    return out

def is_protected_tool(tool_name:str, config:dict[str,Any])->bool:
    protected={alias for item in get_in(config,"verification.protected_tools",[]) or [] for alias in _tool_aliases(str(item))}
    return any(alias in protected for alias in _tool_aliases(tool_name))

def _command_like_arg_key(name:str)->bool:
    key=_norm(name)
    if not key or key in _SHELL_TEXT_ONLY_KEYS: return False
    return key in _SHELL_ARG_KEYS or any(marker in key for marker in ("command","script","shell","stdin"))

def _looks_like_human_slug(token:str)->bool:
    value=str(token or "").strip()
    if not _SLUG_TOKEN_RE.fullmatch(value): return False
    parts=[p for p in re.split(r"[_-]+", value) if p]
    alpha_parts=[p for p in parts if p.isalpha()]
    return len(alpha_parts) >= 3 and sum(ch.isdigit() for ch in value) <= 6

def _has_secret_like_value(text:str)->bool:
    if _SECRET_RE.search(text): return True
    for match in _LONG_SECRET_RE.finditer(text):
        token=match.group(0)
        if _UUID_RE.fullmatch(token) or _looks_like_human_slug(token): continue
        return True
    return False

def extract_shell_commands(tool_name:str, tool_args:dict[str,Any])->list[str]:
    args=tool_args if isinstance(tool_args,dict) else {}; commands=[]
    for k,v in args.items():
        if _command_like_arg_key(str(k)): commands.extend([s for s in _strings(v) if s.strip()])
    return commands

def _strip_heredocs(command:str)->str:
    lines=str(command or "").splitlines(); out=[]; i=0
    while i < len(lines):
        line=lines[i]; out.append(line); m=_HEREDOC_RE.search(line)
        if m:
            delim=m.group("name"); i+=1
            while i < len(lines) and lines[i].strip()!=delim: i+=1
            if i < len(lines): i+=1
        else: i+=1
    return "\n".join(out)

def _tokens(command:str)->list[str]:
    sanitized=_strip_heredocs(command); spaced=re.sub(r"(\|\||&&|>>|<<|[|;&()<>])", r" \1 ", sanitized)
    try:
        lx=shlex.shlex(spaced,posix=True); lx.whitespace_split=True; lx.commenters=""; return list(lx)
    except Exception:
        try: return shlex.split(sanitized,posix=True)
        except Exception: return sanitized.split()

def _segments(tokens:list[str])->list[list[str]]:
    segs=[]; cur=[]
    for t in tokens:
        if t in {"|",";","&&","||","(",")"}:
            if cur: segs.append(cur); cur=[]
            segs.append([t])
        else: cur.append(t)
    if cur: segs.append(cur)
    return segs

def _basename(t:str)->str: return str(t or "").split("/")[-1].lower()
def _unwrap(seg:list[str])->list[str]:
    seg=list(seg)
    while seg and _basename(seg[0]) in {"sudo","doas","command"}: seg=seg[1:]
    if seg and _basename(seg[0])=="env": seg=[t for t in seg[1:] if "=" not in t]
    return seg

def _flag_chars(tokens:list[str])->str: return "".join(t.lstrip("-") for t in tokens if t.startswith("-") and not t.startswith("--"))
def _short_flag_has(flag_token:str, flag:str)->bool:
    token=str(flag_token or "")
    return token.startswith("-") and not token.startswith("--") and flag in token[1:]
def _targets(seg:list[str])->list[str]:
    out=[]; skip=False
    for i,t in enumerate(seg[1:],start=1):
        if skip: skip=False; continue
        if t in {">",">>","<","<<"}: skip=True; continue
        if t.startswith("-") or (i>0 and seg[i-1] in {"-c","--command"}): continue
        out.append(t)
    return out

def _clean_path(p:str)->str: return str(p or "").strip().strip('"\'')
def _normalize_path(p:str)->str:
    path=_clean_path(p)
    return posixpath.normpath(path) if path else ""
def _path_candidates(p:str)->list[str]:
    raw=_clean_path(p)
    if not raw: return []
    candidates={raw,_normalize_path(raw)}
    for suffix in ("/*","/**","/.","/.//"):
        if raw.endswith(suffix):
            base=raw[:-len(suffix)] or "/"
            candidates.add(base); candidates.add(_normalize_path(base))
    return [c for c in candidates if c]
def _protected_paths(config:dict[str,Any], scope:dict[str,Any]|None=None)->list[str]:
    scope=scope or {}; out=[]
    for value in get_in(config,"verification.protected_paths",[]) or []:
        path=_normalize_path(str(value))
        if path: out.append(path)
    project=scope.get("project")
    if isinstance(project,str):
        path=_normalize_path(project)
        if path.startswith("/"): out.append(path)
    return list(dict.fromkeys(out))
def _matches_protected_path(path:str, protected:str)->bool:
    return path==protected or (path != "/" and protected.startswith(path.rstrip("/")+"/"))
def _danger_path(p:str, config:dict[str,Any], scope:dict[str,Any]|None=None)->bool:
    for candidate in _path_candidates(p):
        if candidate in {"/","/*","//",".","..","./","../","~","~/"} or candidate.startswith("/*"): return True
        normalized=_normalize_path(candidate)
        if normalized in {"/",".",".."}: return True
        if any(_matches_protected_path(normalized, protected) for protected in _protected_paths(config, scope)): return True
    return False

def _rm_rf_target(seg:list[str], config:dict[str,Any], scope:dict[str,Any]|None=None)->str|None:
    seg=_unwrap(seg)
    if not seg or _basename(seg[0])!="rm": return None
    flags=_flag_chars(seg[1:]); rec="r" in flags or any(t in {"-R","--recursive"} for t in seg[1:]); forced="f" in flags or "--force" in seg[1:]
    if not (rec and forced): return None
    for target in _targets(seg):
        if _danger_path(target, config, scope): return _clean_path(target)
    return None

def _chmod_777_target(seg:list[str], config:dict[str,Any], scope:dict[str,Any]|None=None)->str|None:
    seg=_unwrap(seg)
    if not seg or _basename(seg[0])!="chmod": return None
    rec=any(t=="-R" or t=="--recursive" or (t.startswith("-") and "R" in t) for t in seg[1:]); seven=any(t=="777" for t in seg[1:])
    if not (rec and seven): return None
    for target in _targets(seg):
        if _danger_path(target, config, scope): return _clean_path(target)
    return None

def _curl_pipe_shell(segs:list[list[str]])->bool:
    for i,seg in enumerate(segs[:-1]):
        seg=_unwrap(seg)
        if not seg or _basename(seg[0]) not in _DOWNLOADERS: continue
        for nxt in segs[i+1:i+3]:
            if nxt and nxt[0] in {"|",";","&&","||"}: continue
            nxt=_unwrap(nxt)
            return bool(nxt and _basename(nxt[0]) in _SHELLS)
    return False

def _shell_command_payloads(seg:list[str])->list[str]:
    seg=_unwrap(seg)
    if not seg or _basename(seg[0]) not in _SHELLS: return []
    payloads=[]
    for i,t in enumerate(seg[:-1]):
        if t in {"-c","--command"} or _short_flag_has(t,"c"):
            payloads.append(seg[i+1])
    return payloads

def _redirection_targets(seg:list[str])->list[str]:
    out=[]; seg=list(seg)
    for i,t in enumerate(seg[:-1]):
        if t in {">",">>","<","<<"}: out.append(seg[i+1])
    return out

def _merge_shell_analysis(target:ShellAnalysis, nested:ShellAnalysis)->None:
    target.executable_segments.extend(nested.executable_segments)
    target.normalized_operations.extend(nested.normalized_operations)
    target.redirection_targets.extend(nested.redirection_targets)
    target.risk_categories.extend(nested.risk_categories)
    target.notes.extend(nested.notes)
    if nested.matched_blocked_pattern and not target.matched_blocked_pattern:
        target.matched_blocked_pattern=nested.matched_blocked_pattern

def _normalized_json(value:Any)->str:
    try: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception: return str(value)

def build_verification_cache_key(tool_name:str, tool_args:dict[str,Any], config_hash:str, spec_version:str, scope:dict[str,Any]|None=None)->str:
    return stable_hash(_VERIFICATION_CACHE_KEY_VERSION, tool_name, _normalized_json(tool_args or {}), config_hash, spec_version, _normalized_json(scope or {}))

def _analyze_shell_command(command:str, config:dict[str,Any], patterns:list[str], scope:dict[str,Any]|None=None, seen:set[str]|None=None)->ShellAnalysis:
    seen=seen or set(); a=ShellAnalysis(raw_commands=[command]); marker=str(command or "").strip()
    if marker in seen:
        a.notes.append("skipped recursive shell payload already analyzed")
        return a
    seen.add(marker)
    segs=[_unwrap(s) if s and s[0] not in {"|",";","&&","||"} else s for s in _segments(_tokens(command))]
    a.executable_segments.extend(segs)
    a.normalized_operations.extend(" ".join(s) for s in segs if s and s[0] not in {"|",";","&&","||"})
    for s in segs:
        if s and s[0] not in {"|",";","&&","||"}: a.redirection_targets.extend(_redirection_targets(s))
    for s in segs:
        for payload in _shell_command_payloads(s):
            nested=_analyze_shell_command(payload, config, patterns, scope, seen)
            nested.notes.append(f"unwrapped shell command payload from {' '.join(_unwrap(s)[:2])}".strip())
            _merge_shell_analysis(a, nested)
            if a.matched_blocked_pattern: return a
    for s in segs:
        target=_rm_rf_target(s, config, scope)
        if target:
            a.matched_blocked_pattern=f"rm -rf {target}"; a.risk_categories.append("destructive_file_edit"); return a
    for s in segs:
        target=_chmod_777_target(s, config, scope)
        if target:
            a.matched_blocked_pattern=f"chmod -R 777 {target}"; a.risk_categories.append("destructive_file_edit"); return a
    if _curl_pipe_shell(segs): a.matched_blocked_pattern="curl * | sh"; a.risk_categories.append("remote_code_execution"); return a
    for pat in patterns:
        p=_collapse(pat)
        if p in {"rm -rf /","chmod -r 777 /","curl * | sh"}: continue
        for op in a.normalized_operations:
            o=_collapse(op)
            if p and (p in o or fnmatch(o,p)): a.matched_blocked_pattern=pat; a.risk_categories.append("configured_shell_pattern"); return a
    return a

@dataclass
class ShellAnalysis:
    raw_commands:list[str]=field(default_factory=list); executable_segments:list[list[str]]=field(default_factory=list); normalized_operations:list[str]=field(default_factory=list); redirection_targets:list[str]=field(default_factory=list); matched_blocked_pattern:str|None=None; risk_categories:list[str]=field(default_factory=list); notes:list[str]=field(default_factory=list)
    def to_dict(self)->dict[str,Any]: return {"raw_commands":self.raw_commands,"executable_segments":self.executable_segments,"normalized_operations":self.normalized_operations,"redirection_targets":self.redirection_targets,"matched_blocked_pattern":self.matched_blocked_pattern,"risk_categories":self.risk_categories,"notes":self.notes}

def analyze_executable_shell(tool_name:str, tool_args:dict[str,Any], config:dict[str,Any], *, scope:dict[str,Any]|None=None)->ShellAnalysis:
    a=ShellAnalysis(); commands=extract_shell_commands(tool_name,tool_args); a.raw_commands=commands; patterns=[str(i) for i in get_in(config,"verification.blocked_shell_patterns",[]) or []]
    for cmd in commands:
        nested=_analyze_shell_command(cmd, config, patterns, scope)
        _merge_shell_analysis(a, nested)
        if a.matched_blocked_pattern: return a
    return a

def extract_urls(tool_args:dict[str,Any])->list[str]:
    seen=set(); out=[]
    for text in _strings(tool_args):
        for url in _URL_RE.findall(text):
            if url not in seen: seen.add(url); out.append(url)
    return out

def _match_domain(host:str, domains:list[str])->bool:
    h=host.lower().lstrip(".")
    return any(h==(d or "").lower().lstrip(".") or h.endswith("."+(d or "").lower().lstrip(".")) for d in domains if d)

def analyze_file_destination(tool_name:str, tool_args:dict[str,Any], shell:ShellAnalysis, config:dict[str,Any], *, scope:dict[str,Any]|None=None)->dict[str,Any]:
    args=tool_args if isinstance(tool_args,dict) else {}; dest=list(shell.redirection_targets)
    for k in ("path","file","filepath","filename","destination","output_path"):
        if isinstance(args.get(k),str): dest.append(args[k])
    text=" ".join(_strings({k:v for k,v in args.items() if k not in {"content","text","payload","body"}}, include_keys=True)).lower()
    return {"destinations":dest,"destructive":_norm(tool_name) in {"text_editor","editor","write_file"} and any(m in text for m in ["overwrite","replace","delete","remove","truncate"]),"protected_destination":any(_danger_path(d, config, scope) for d in dest)}

def analyze_content_payload(tool_name:str, tool_args:dict[str,Any])->dict[str,Any]:
    args=tool_args if isinstance(tool_args,dict) else {}; payload="\n".join(s for k,v in args.items() if str(k).lower() in {"content","text","body","payload","message","data"} for s in _strings(v))
    return {"has_payload":bool(payload),"payload_chars":len(payload),"mentions_shell_danger_text":bool(re.search(r"rm\s+-[A-Za-z]*rf|chmod\s+-R\s+777", payload)),"note":"payload text is not treated as executable shell by itself"}

def analyze_credential_likelihood(tool_name:str, tool_args:dict[str,Any])->dict[str,Any]:
    args=tool_args if isinstance(tool_args,dict) else {}; keys=[]; hits=0
    for k,v in args.items():
        if _SECRET_RE.search(str(k)): keys.append(str(k))
        for text in _strings(v):
            if _has_secret_like_value(text): hits+=1
    return {"key_hits":keys,"value_hit_count":hits,"likely_secret":bool(keys or hits)}

class VerificationGuardian:
    def __init__(self, config:dict[str,Any]|None=None): self.config=config if isinstance(config,dict) else {}
    def verify_tool(self, context:AgentContext, tool:ToolInvocation)->VerificationResult: return self._verify(tool.tool_name,tool.tool_args or {},context.config or self.config,scope=context.scope)
    def verify_tool_args(self,tool_name:str,tool_args:dict[str,Any],config:dict[str,Any]|None=None,*,scope:dict[str,Any]|None=None)->VerificationResult: return self._verify(tool_name,tool_args or {},config or self.config,scope=scope or {})
    def _verify(self,tool_name:str,tool_args:dict[str,Any],config:dict[str,Any],*,scope:dict[str,Any]|None=None)->VerificationResult:
        mode=layer_mode(config,"verification",default="enforce"); tool=_norm(tool_name); protected=is_protected_tool(tool_name,config); verification_cfg=config.get("verification",{}) if isinstance(config.get("verification",{}),dict) else {}; spec_version=str(get_in(config,"plugin.spec_version","1.0.0") or "1.0.0"); config_hash=verification_cache_hash(config); cache_enabled=bool(verification_cfg.get("cache_enabled",False)); cache_key=build_verification_cache_key(tool_name, tool_args, config_hash, spec_version, scope or {}); r=VerificationResult(tool_name=tool_name,action="allow",reason="structured verification pending",risk_score=0,policy_mode=mode,scope=scope or {},cache_key=cache_key,cache_status="miss")
        if mode=="off": r.reason="verification mode off"; return r
        if cache_enabled:
            if bool(verification_cfg.get("invalidate_on_config_change", True)):
                state.invalidate_verification_cache(config_hash=config_hash, spec_version=spec_version)
            cached = state.get_verification_cache_entry(cache_key)
            if cached:
                decision=self._decision_from_cache(cached.get("decision",{}) or {})
                return VerificationResult(**{**decision,"tool_name":tool_name,"scope":scope or {}, "cached":True,"cache_key":cache_key,"cache_status":"hit"})
        r.reason="structured verification in progress"; r.risk_score=15 if protected else 5
        if tool=="code_execution_tool": r.risk_score=max(r.risk_score,70)
        shell=analyze_executable_shell(tool_name,tool_args,config,scope=scope); fd=analyze_file_destination(tool_name,tool_args,shell,config,scope=scope); payload=analyze_content_payload(tool_name,tool_args); cred=analyze_credential_likelihood(tool_name,tool_args)
        r.analysis={"tool_policy":{"is_protected_tool":protected,"default_high_risk":tool=="code_execution_tool"},"shell":shell.to_dict(),"file_destination":fd,"content_payload":payload,"credential_likelihood":cred,"cache":{"enabled":cache_enabled,"key":cache_key,"config_hash":config_hash,"spec_version":spec_version}}
        if shell.matched_blocked_pattern:
            r.action="block" if mode=="enforce" else "warn"; r.reason="matched blocked shell operation"; r.risk_score=95; r.matched_blocked_shell_pattern=shell.matched_blocked_pattern; r.risk_categories=sorted(set(shell.risk_categories or ["destructive_file_edit"])); return self._store_cached_result(r, cache_enabled, config_hash, spec_version)
        blocked=get_in(config,"verification.blocked_domains",[]) or []; allowed=get_in(config,"verification.allowed_domains",[]) or []
        for url in extract_urls(tool_args):
            host=(urlparse(url).hostname or "").lower()
            if host and _match_domain(host,blocked): r.action="block" if mode=="enforce" else "warn"; r.reason="matched blocked domain"; r.risk_score=85; r.matched_blocked_domain=host; r.risk_categories=["external_write"]; return self._store_cached_result(r, cache_enabled, config_hash, spec_version)
            if host and allowed and tool in {"browser_agent","browser","web"} and not _match_domain(host,allowed): r.action="block" if mode=="enforce" else "warn"; r.reason="domain not in allowlist"; r.risk_score=72; r.matched_allowlist_miss=host; r.risk_categories=["external_write"]
        cats=[]
        if fd.get("destructive") or fd.get("protected_destination"): cats.append("destructive_file_edit")
        text=" ".join(_strings({k:v for k,v in (tool_args or {}).items() if str(k).lower() not in {"content","text","body","payload"}}, include_keys=True)).lower()
        if any(m in text for m in ["post","put","patch","delete","upload","submit"]): cats.append("external_write")
        if cred.get("likely_secret"): cats.append("credential_exposure")
        r.risk_categories=sorted(set(cats)); review=set(get_in(config,"verification.require_review_for",[]) or []); enforce_review=protected or tool=="code_execution_tool"
        if enforce_review and review.intersection(r.risk_categories): r.risk_score=max(r.risk_score,78); r.action="block" if mode=="enforce" else "warn"; r.reason="matched configured review category"
        if enforce_review and "credential_exposure" in r.risk_categories: r.risk_score=max(r.risk_score,88); r.action="block" if mode=="enforce" else "warn"; r.reason="possible credential exposure"
        if r.risk_score > int(get_in(config,"verification.max_risk_score",70) or 70) and r.action=="allow": r.action="block" if mode=="enforce" else "warn"; r.reason="risk score exceeds configured maximum"
        if r.action=="allow": r.reason="tool allowed after structured checks"; r.risk_score=max(r.risk_score,20)
        return self._store_cached_result(r, cache_enabled, config_hash, spec_version)
    def _store_cached_result(self, result:VerificationResult, cache_enabled:bool, config_hash:str, spec_version:str)->VerificationResult:
        if not cache_enabled:
            return result
        ttl_seconds=int(get_in(self.config,"verification.cache_ttl_seconds",300) or 300)
        created_at=utc_now_iso()
        expires_at=(state.utc_now()+timedelta(seconds=max(1, ttl_seconds))).isoformat()
        decision={k:v for k,v in result.to_dict().items() if k not in {"layer","tool"}}
        decision["cached"]=False
        decision["cache_status"]="stored"
        entry=VerificationCacheEntry(key=str(result.cache_key or ""),tool_name=result.tool_name,scope=result.scope,config_hash=config_hash,spec_version=spec_version,decision=decision,created_at=created_at,expires_at=expires_at)
        state.put_verification_cache_entry(entry.to_dict())
        result.cache_status="stored"
        return result
    def _decision_from_cache(self, value:dict[str,Any])->dict[str,Any]:
        allowed={"action","reason","risk_score","risk_categories","matched_blocked_shell_pattern","matched_blocked_domain","matched_allowlist_miss","analysis","policy_mode","scope","cached","cache_key","cache_status","timestamp"}
        return {k:v for k,v in dict(value or {}).items() if k in allowed}
    def get_policy_snapshot(self)->dict[str,Any]: return {"mode":layer_mode(self.config,"verification",default="enforce"),"protected_tools":get_in(self.config,"verification.protected_tools",[]) or [],"protected_paths":get_in(self.config,"verification.protected_paths",[]) or [],"blocked_shell_patterns":get_in(self.config,"verification.blocked_shell_patterns",[]) or [],"cache_enabled":bool(get_in(self.config,"verification.cache_enabled",False)),"cache_ttl_seconds":int(get_in(self.config,"verification.cache_ttl_seconds",0) or 0)}

def evaluate_tool_call(tool_name:str, tool_args:dict[str,Any], config:dict[str,Any], *, agent:Any|None=None)->dict[str,Any]: return VerificationGuardian(config).verify_tool_args(tool_name, tool_args or {}, config, scope=scope_for_agent(agent)).to_dict()
