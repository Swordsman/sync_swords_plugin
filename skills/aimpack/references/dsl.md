S-expressions are the sole instruction representation. No NL mirror. NL is leaf content inside functional forms. Turing-complete with bounds.

Vocabulary: `(task "...")` unit of work, `(pipeline name ...)` sequential, `(par ...)` parallel fork-join, `(let name expr body)` bind, `(infer agent action inputs)` LLM call, `(exec handler args)` procedural, `(if cond then else)`, `(when cond body)`, `(loop binding body)` bounded iteration, `(recur args)` tail recursion within loop, `(fuel n body)` step limit, `(on-error hint body)` soft hint (optional, not control flow), `(file "path")` / `(files ...)` refs, `(emit result ...)` output, `(retry :max N)`, `(checkpoint "name")`, `(defcontract name :accepts ... :produces ... :constraints ...)` / `(apply-contract name)`.

Keyword args use `:key value` pairs: `(infer claude (analyze :domain security :focus xss) (files "src/main.py"))`. Actions are functional forms, not strings: `(analyze ...)`, `(transform ...)`, `(generate ...)`.

Contracts are advisory pre/post conditions. Agent interprets compliance. Checkpoints are named restore points for squash/truncate, not serialization boundaries.

Error model is implicit: the executing agent (an LLM) catches exceptions and recovers. `(on-error)` provides optional soft hints, not mandatory control flow.

```lisp
;; Simple — bare task, no routing
(task "review src/auth.py for security issues")

;; Orchestrated — multi-agent with contracts, fuel-bounded
(pipeline "refactor auth"
  (defcontract code-review
    :accepts (files :type source-code)
    :produces (annotations :type issue-list))
  (let issues
    (infer claude
      (apply-contract code-review)
      (files "src/auth.py" "src/oauth.py")
      :focus (security timing-attacks))
    (fuel 3
      (par
        (infer gemini
          (transform :from issues :action rewrite :constraint preserve-api)
          :output (file "src/auth.py"))
        (infer claude
          (generate :type tests :coverage each-fix :from issues)
          :output (file "tests/test_auth.py"))))
    (checkpoint "refactor-complete")))

;; Iteration with fuel bound
(fuel 10
  (loop (i 0)
    (when (< i (len items))
      (infer claude (process (nth items i)))
      (recur (+ i 1)))))
```

## Extensions

Handlers in `~/.aimpack/extensions/*.py` register for Content-Types. Resolution chain (configurable in `~/.aimpack/config.json`): local → github manifest → web → diagnostic (never blocks). `aimpack ext install <url>`, `ext list`, `ext resolve <content-type>`.

Handler interface:
```python
CONTENT_TYPES = ["application/x-custom"]
FILE_EXTENSIONS = [".custom"]  # for on_pack file-type matching
def on_pack(filepath, metadata): ...    # returns (headers_dict, body_str)
def on_unpack(headers, body, dest): ... # extract/process
def on_display(headers, body): ...      # returns summary string for log
```

Config (`~/.aimpack/config.json`):
```json
{"resolver": {"chain": ["local","github","web","ask"], "local_paths": ["~/.aimpack/extensions"], "github_repos": ["swordsman/aimpack"], "auto_install": false}}
```
