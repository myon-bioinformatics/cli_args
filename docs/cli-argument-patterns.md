# CLI argument patterns worth preserving

This repository treats command-line options as reusable **behavior contracts**, not as trivia.
The goal is to prefer options that improve readability, determinism, failure handling, machine parsing,
or safe filename/value transport.

Use four evidence labels consistently:

- **Host-real**: executed on the CI host.
- **Container-real**: executed inside the pinned test image.
- **System-service-real**: executed against the real backing service/state.
- **Construct-only**: exact argv is fixed, but the tool/service is not claimed as exercised.

## Selection: ask the CLI to select exactly what you mean

| Tool | Pattern | Why it is useful |
|---|---|---|
| `sed` | `-n '4,6p'` | Print only a numeric line range instead of post-filtering output. |
| `sed` (GNU) | `-n '4,+2p'` | Express "this line and the next N lines" directly. |
| `grep` | `-F -x -m 1 -- PATTERN FILE` | Literal match + whole-line match + bounded work + explicit option boundary. |
| pytest | `-k "expr"`, `--tb=short`, `--maxfail=1` | Select relevant tests, shorten diagnostics, and stop early when appropriate. |
| Playwright | `--grep`, `--project=chromium`, `--list`, `--last-failed` | Select tests/projects or collect/rerun without broad execution. |

Official references:
- GNU sed: https://www.gnu.org/software/sed/manual/sed.html
- GNU grep: https://www.gnu.org/software/grep/manual/grep.html
- pytest: https://docs.pytest.org/
- Playwright Test CLI: https://playwright.dev/docs/test-cli

## Machine-readable output: do not scrape human presentation when a contract exists

| Tool | Pattern | Why it is useful |
|---|---|---|
| Git | `status --porcelain=v2 -z --branch` | Stable status format with NUL-safe paths and branch metadata. |
| Git | `for-each-ref --format=... --sort=...` | Ask Git to format refs directly; `%00` can emit NUL. |
| Git | `ls-files -z` | NUL-safe tracked path output. |
| curl | `--write-out '%{http_code}'` | Emit request metadata explicitly instead of parsing verbose text. |
| gh | `api --jq ...` | Filter structured API output at the CLI boundary. |

Official references:
- Git status: https://git-scm.com/docs/git-status
- Git for-each-ref: https://git-scm.com/docs/git-for-each-ref
- curl: https://curl.se/docs/manpage.html
- GitHub CLI API: https://cli.github.com/manual/gh_api

## Safe filename/value transport: prefer NUL when newline or spaces are data

| Tool | Pattern | Why it is useful |
|---|---|---|
| `find` | `-print0` | Filename records are terminated by NUL, not whitespace/newline. |
| `xargs` | `-0` / `--null` | Consume NUL records without interpreting quotes/backslashes specially. |
| `xargs` | `-a FILE` / `--arg-file=FILE` | Read arguments from a file while leaving child stdin independent. |
| `sort` | `-z` | Sort NUL-terminated records. |
| `grep` | `-Z` | NUL-terminate printed filenames. |

The safe pipeline idea is:

`find ... -print0` -> NUL-aware consumer such as `xargs -0`, `sort -z`, or another parser.

Official references:
- GNU findutils safe filenames: https://www.gnu.org/software/findutils/manual/html_node/find_html/Safe-File-Name-Handling.html
- GNU xargs options: https://www.gnu.org/software/findutils/manual/html_node/find_html/xargs-options.html

## Failure behavior: make failure intentional and machine-visible

| Tool | Pattern | Why it is useful |
|---|---|---|
| curl | `--fail-with-body` | Keep an HTTP error body while still returning a failing exit status. |
| curl | `--fail-early` | Stop a multi-transfer invocation at the first transfer failure. |
| pytest | `--maxfail=1` | Bound follow-on noise after a meaningful failure. |
| Playwright | `--forbid-only` | Turn accidental `test.only` into a CI failure. |
| Playwright | `--last-failed` | Rerun the failure set instead of rediscovering it manually. |

A good automation option usually does one of these:
1. makes success/failure explicit;
2. bounds work;
3. produces stable machine output;
4. preserves data characters exactly;
5. avoids shell quoting/splitting;
6. exposes provenance or selection directly.

## Exit-code contracts: let status mean something

For automation, "nothing printed" and "nothing changed" should not be inferred from prose when the CLI already
defines an exit contract.

| Tool | Pattern | Useful contract |
|---|---|---|
| Git | `diff --quiet --no-ext-diff --no-textconv -- PATH` | exit 0 = no diff, exit 1 = diff; no human diff text needs parsing. |
| Git | `ls-files --error-unmatch -- PATH` | exit 0 = tracked/index match, exit 1 = not present in the index. |
| `grep` | `-q` | match/no-match can be used as a branch condition without output. |
| `sort` | `-C` | validate ordering without printing the sorted data. |
| `xargs` | `-r` / `--no-run-if-empty` | empty input does not invoke the child command at all. |
| pytest | `--collect-only -q` | inspect/select the test set without executing tests. |
| pytest | `--maxfail=1` | bound noisy follow-on failures while preserving a failing exit status. |

Official references:
- Git diff options: https://git-scm.com/docs/diff-options
- Git ls-files: https://git-scm.com/docs/git-ls-files
- pytest reference: https://docs.pytest.org/en/stable/reference/reference.html
- GNU grep: https://www.gnu.org/software/grep/manual/grep.html
- GNU coreutils sort: https://www.gnu.org/software/coreutils/manual/coreutils.html
- GNU xargs: https://www.gnu.org/software/findutils/manual/html_node/find_html/xargs-options.html

## Reproducibility and isolation: make policy visible in argv

Useful command options can carry operational policy directly, which is much easier to audit than hidden shell
state or environment assumptions.

| Tool | Pattern | Why it matters |
|---|---|---|
| GNU tar | `--sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner` | normalize order, timestamps and ownership for reproducible archives. |
| gzip | `-n` / `--no-name` | omit original filename/timestamp metadata from compressed output. |
| Docker | `--pull=never` | require the already-built local image; never hide a registry pull. |
| Docker | `--network=none` | make "this test does not need network" an executable policy. |
| Docker | `--read-only --tmpfs /tmp:...` | read-only root filesystem with an explicit bounded writable scratch area. |

The Docker evidence in this repository combines those flags with the locally-built test image. The test succeeds
only if the local image is sufficient, the root filesystem can stay read-only, and the declared tmpfs provides the
required scratch write.

Official references:
- Docker run: https://docs.docker.com/reference/cli/docker/container/run/
- GNU tar reproducibility: https://www.gnu.org/software/tar/manual/html_node/Reproducibility.html
- GNU gzip: https://www.gnu.org/software/gzip/manual/gzip.html

## Modern search tools: keep the same machine-oriented philosophy

Modern CLIs often expose structured output that is safer than parsing their default terminal presentation.

| Tool | Pattern | Why it is useful |
|---|---|---|
| ripgrep | `--json PATTERN PATH` | emit structured begin/match/end/summary events as JSON Lines. |
| ripgrep | `-0 -l PATTERN PATH` | emit matching filenames with NUL terminators. |

This complements classic `grep -Z` / `find -print0`: newer tools should not cause the project to abandon the
same machine-readable and NUL-safe contracts.

Reference:
- ripgrep guide/source: https://github.com/BurntSushi/ripgrep

## Batch / stdin-oriented options

Some excellent CLI features require non-interactive stdin or a batch protocol:

- Git `--pathspec-from-file=- --pathspec-file-nul`
- Git `cat-file --batch-command --buffer -Z`
- `xargs -0` from stdin

These are valuable, but `cli_args` must not claim them as real execution until its runtime contract deliberately
supports bounded stdin/batch input. Until then, keep exact argv as **Construct-only** evidence.

## Rule of thumb for AI coding

Prefer, in order:

1. an existing machine-oriented option from the target CLI;
2. Python stdlib when it already expresses the operation safely;
3. a thin `Command` argv wrapper;
4. only then custom parsing, shell glue, or a new abstraction.

The repository should keep adding obscure-but-useful options when they improve reliability, readability,
or reproducibility—not merely because they are uncommon.
