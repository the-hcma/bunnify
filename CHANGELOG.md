# Changelog

## [0.15.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.14.0...bunnify-v0.15.0) (2026-09-19)


### Features

* add windows extra and CLI foundation for Spotty Bunny ([#425](https://github.com/the-hcma/bunnify/issues/425)) ([#430](https://github.com/the-hcma/bunnify/issues/430)) ([217446c](https://github.com/the-hcma/bunnify/commit/217446c6ba46d3564a795878aa8dfc665d4b6e7b))
* bunnify upgrade refreshes the Windows Scheduled Task too ([#467](https://github.com/the-hcma/bunnify/issues/467)) ([#470](https://github.com/the-hcma/bunnify/issues/470)) ([97740f7](https://github.com/the-hcma/bunnify/commit/97740f767fc0f5173cbc978b69f1272b0791b022))
* offer to install Spotty Bunny during setup, on both platforms ([#467](https://github.com/the-hcma/bunnify/issues/467)) ([#469](https://github.com/the-hcma/bunnify/issues/469)) ([667a87c](https://github.com/the-hcma/bunnify/commit/667a87cb8426219cf1babf632e5af02c782b65f9))
* Windows global hotkey capture via WH_KEYBOARD_LL ([#424](https://github.com/the-hcma/bunnify/issues/424)) ([#432](https://github.com/the-hcma/bunnify/issues/432)) ([983e32f](https://github.com/the-hcma/bunnify/commit/983e32fa6f216454fcdc845c101ac069448bf7ef))
* Windows Spotty Bunny About panel ([#428](https://github.com/the-hcma/bunnify/issues/428)) ([#440](https://github.com/the-hcma/bunnify/issues/440)) ([4dbcff0](https://github.com/the-hcma/bunnify/commit/4dbcff0a3a4923d86588061cf499030196c7d080))
* Windows Spotty Bunny overlay polish ([#437](https://github.com/the-hcma/bunnify/issues/437)) ([#463](https://github.com/the-hcma/bunnify/issues/463)) ([6404eac](https://github.com/the-hcma/bunnify/commit/6404eace59580e49bb02a9744f5609c0dc5e637e))
* Windows Spotty Bunny startup update-status ([#436](https://github.com/the-hcma/bunnify/issues/436)) ([#462](https://github.com/the-hcma/bunnify/issues/462)) ([ce85ed8](https://github.com/the-hcma/bunnify/commit/ce85ed8da5f9d567a83f9df6a952af20a8e53834))
* Windows tray icon + overlay search window ([#426](https://github.com/the-hcma/bunnify/issues/426)) ([#435](https://github.com/the-hcma/bunnify/issues/435)) ([980d9b2](https://github.com/the-hcma/bunnify/commit/980d9b298144b7c227047ef508d6ce974c1e0311))


### Bug Fixes

* fall back to a plain label if SysLink is unavailable ([#441](https://github.com/the-hcma/bunnify/issues/441)) ([#466](https://github.com/the-hcma/bunnify/issues/466)) ([705338a](https://github.com/the-hcma/bunnify/commit/705338a80a0cdcb634fc9e2ad296e3928610457e))
* platform-neutral skew/version wording ([#467](https://github.com/the-hcma/bunnify/issues/467)) ([#468](https://github.com/the-hcma/bunnify/issues/468)) ([2cf3bb4](https://github.com/the-hcma/bunnify/commit/2cf3bb4eb763c5990c2819d11f4e32e541d5e449))
* preserve last-known-good LaunchAgent plist on failed restore ([#422](https://github.com/the-hcma/bunnify/issues/422)) ([63136e2](https://github.com/the-hcma/bunnify/commit/63136e2c8aadd7c8703fd67a70881e7b9eee9df3))
* stop stale local server when switching setup mode to remote ([#421](https://github.com/the-hcma/bunnify/issues/421)) ([2cb543c](https://github.com/the-hcma/bunnify/commit/2cb543c4ee573d153ab2e6c400f186c05a332461))
* Windows test-suite compatibility across 5 modules ([#431](https://github.com/the-hcma/bunnify/issues/431)) ([#434](https://github.com/the-hcma/bunnify/issues/434)) ([a31a05a](https://github.com/the-hcma/bunnify/commit/a31a05aa7132dda35b1334bdbe2689bef8515906))


### Documentation

* Windows Spotty Bunny install docs + permissions note ([#429](https://github.com/the-hcma/bunnify/issues/429)) ([#442](https://github.com/the-hcma/bunnify/issues/442)) ([ac12f9f](https://github.com/the-hcma/bunnify/commit/ac12f9f6813b3bf86caefd9bb2993430b97f55f7))

## [0.14.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.13.1...bunnify-v0.14.0) (2026-09-15)


### Features

* harden LaunchAgent upgrade rollback and add `bunnify status` ([#419](https://github.com/the-hcma/bunnify/issues/419)) ([a2b1334](https://github.com/the-hcma/bunnify/commit/a2b13341dae8212aa68d64ce97459911f41b8033))
* make the spotty-bunny hotkey configurable and migrate config to TOML ([#415](https://github.com/the-hcma/bunnify/issues/415)) ([72806ad](https://github.com/the-hcma/bunnify/commit/72806ad3402103e4225d80aa35342daae5ebb6c6))

## [0.13.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.13.0...bunnify-v0.13.1) (2026-09-12)


### Bug Fixes

* **spotty-bunny:** reflect self-staleness in the update badge, not just PyPI ([#411](https://github.com/the-hcma/bunnify/issues/411)) ([1e9a80e](https://github.com/the-hcma/bunnify/commit/1e9a80e0dbfdb379d796dce4c12f90634995c96e))

## [0.13.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.12.1...bunnify-v0.13.0) (2026-09-12)


### Features

* **cli:** emit shell completion via `bunnify --completion <shell>` ([#406](https://github.com/the-hcma/bunnify/issues/406)) ([a0be6d5](https://github.com/the-hcma/bunnify/commit/a0be6d51b0d516090cdd4351666c9f2c73083ba2))


### Documentation

* hyperlink the GitHub handle in the README license notice ([#407](https://github.com/the-hcma/bunnify/issues/407)) ([949a652](https://github.com/the-hcma/bunnify/commit/949a652015329933b27de08230e847939b0e84ee))
* **rules:** adopt dedicated github-api-throttle rule (repository-helpers[#608](https://github.com/the-hcma/bunnify/issues/608)) ([#402](https://github.com/the-hcma/bunnify/issues/402)) ([5ca58cc](https://github.com/the-hcma/bunnify/commit/5ca58cce44344418816e7bf5acb145930bb1b593))

## [0.12.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.12.0...bunnify-v0.12.1) (2026-09-01)


### Bug Fixes

* import NSWorkspaceDidWakeNotification from Cocoa ([#390](https://github.com/the-hcma/bunnify/issues/390)) ([6e81466](https://github.com/the-hcma/bunnify/commit/6e814668fdceb713596678aa0784ef413ab3d87f))

## [0.12.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.11.3...bunnify-v0.12.0) (2026-09-01)


### Features

* auto-heal Spotty Bunny stale event taps ([#388](https://github.com/the-hcma/bunnify/issues/388)) ([5ea1da3](https://github.com/the-hcma/bunnify/commit/5ea1da3027f5e46f66c0f8782f5791ddaed40ce9))

## [0.11.3](https://github.com/the-hcma/bunnify/compare/bunnify-v0.11.2...bunnify-v0.11.3) (2026-08-30)


### Bug Fixes

* confirm configured server mode before setup/upgrade changes ([#384](https://github.com/the-hcma/bunnify/issues/384)) ([506b30d](https://github.com/the-hcma/bunnify/commit/506b30d75743ac94992df78290a759c928fe36a7))

## [0.11.2](https://github.com/the-hcma/bunnify/compare/bunnify-v0.11.1...bunnify-v0.11.2) (2026-08-27)


### Bug Fixes

* qualify the About panel server build-skew warning by mode ([#378](https://github.com/the-hcma/bunnify/issues/378)) ([cf3e3ad](https://github.com/the-hcma/bunnify/commit/cf3e3adb3e292d85fa14d8ccdf3b25718b1eeb89))

## [0.11.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.11.0...bunnify-v0.11.1) (2026-08-27)


### Bug Fixes

* reliably identify Bunnify's own processes (LaunchAgent detection + build marker) ([#369](https://github.com/the-hcma/bunnify/issues/369)) ([85ae6a2](https://github.com/the-hcma/bunnify/commit/85ae6a2a437cad5e45c1a822a544e94927291d8d))

## [0.11.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.10.0...bunnify-v0.11.0) (2026-08-26)


### Features

* unified version coherence for local and remote installs ([#366](https://github.com/the-hcma/bunnify/issues/366)) ([9063b3f](https://github.com/the-hcma/bunnify/commit/9063b3f6bebbccc29088649c27276f766f222c36))

## [0.10.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.9.2...bunnify-v0.10.0) (2026-08-26)


### Features

* LaunchAgent for local server; confirm unreachable remote ([#360](https://github.com/the-hcma/bunnify/issues/360)) ([a6f46da](https://github.com/the-hcma/bunnify/commit/a6f46daedacb5151588362e1f7def01d0cd45190))


### Bug Fixes

* ignore GITHUB_SHA in installed-wheel packaging smoke ([#364](https://github.com/the-hcma/bunnify/issues/364)) ([4a279d0](https://github.com/the-hcma/bunnify/commit/4a279d06de3bf70c23489ce90d721c46ebcc21f0))


### Documentation

* align README and quick reference with server LaunchAgent ([#363](https://github.com/the-hcma/bunnify/issues/363)) ([5dabcc0](https://github.com/the-hcma/bunnify/commit/5dabcc044554a98b0193f6a58910e4207ccf46cd))

## [0.9.2](https://github.com/the-hcma/bunnify/compare/bunnify-v0.9.1...bunnify-v0.9.2) (2026-08-25)


### Bug Fixes

* retry GitHub token for Spotty Bunny Tab completion ([#357](https://github.com/the-hcma/bunnify/issues/357)) ([c2f31c5](https://github.com/the-hcma/bunnify/commit/c2f31c5c320882eb15598fd0bd7a7ac3d1794edf))

## [0.9.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.9.0...bunnify-v0.9.1) (2026-08-22)


### Bug Fixes

* refresh onboard summary after Spotty Bunny install ([#351](https://github.com/the-hcma/bunnify/issues/351)) ([1254d6f](https://github.com/the-hcma/bunnify/commit/1254d6f005f6f734db3a6ca133450e289297785b))
* Spotty Bunny Home/End and empty-Tab browse ([#352](https://github.com/the-hcma/bunnify/issues/352)) ([d1de57a](https://github.com/the-hcma/bunnify/commit/d1de57aeee8b992285738176be5488cbb88bdd5a))

## [0.9.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.8.3...bunnify-v0.9.0) (2026-08-22)


### Features

* seamless macOS onboard and Spotty Bunny install flow ([#348](https://github.com/the-hcma/bunnify/issues/348)) ([55fb2c9](https://github.com/the-hcma/bunnify/commit/55fb2c92ac05553ac9c46f82e98e11a48ae22222))


### Bug Fixes

* decouple onboard upgrade test from release version bumps ([#350](https://github.com/the-hcma/bunnify/issues/350)) ([bd8f51e](https://github.com/the-hcma/bunnify/commit/bd8f51e11eb7185c3617a1d5fa570f3aef8f5a97))

## [0.8.3](https://github.com/the-hcma/bunnify/compare/bunnify-v0.8.2...bunnify-v0.8.3) (2026-08-21)


### Bug Fixes

* keep example bookmarks path in sdist for uv build ([#342](https://github.com/the-hcma/bunnify/issues/342)) ([bab2286](https://github.com/the-hcma/bunnify/commit/bab2286536571afb1c135764508578231eccc881))

## [0.8.2](https://github.com/the-hcma/bunnify/compare/bunnify-v0.8.1...bunnify-v0.8.2) (2026-08-21)


### Bug Fixes

* restore Spotty Bunny clipboard and page navigation ([#338](https://github.com/the-hcma/bunnify/issues/338)) ([664e63a](https://github.com/the-hcma/bunnify/commit/664e63a474602e5729e1c48a587c960dfa3dbffc))

## [0.8.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.8.0...bunnify-v0.8.1) (2026-08-20)


### Bug Fixes

* restore Spotty Bunny Tab completion and Google fallback ([#336](https://github.com/the-hcma/bunnify/issues/336)) ([b69539c](https://github.com/the-hcma/bunnify/commit/b69539c0e081f5e8027fcaf7c23ab07fa9b01deb))

## [0.8.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.7.1...bunnify-v0.8.0) (2026-08-20)


### Features

* declare bookmark placeholder completion kinds in JSON ([#328](https://github.com/the-hcma/bunnify/issues/328)) ([6bf90db](https://github.com/the-hcma/bunnify/commit/6bf90dbda4b04ba7a7e8cdce738bb8131350fa64))
* extend bookmark examples with GitHub complete markers ([#329](https://github.com/the-hcma/bunnify/issues/329)) ([ace673f](https://github.com/the-hcma/bunnify/commit/ace673f7b1720ee38b55fd798a7b47fa257ad5af))


### Bug Fixes

* harden spotty-bunny LaunchAgent install and TCC handling ([#330](https://github.com/the-hcma/bunnify/issues/330)) ([aa5d766](https://github.com/the-hcma/bunnify/commit/aa5d76615ff0b1cf80e26881c52a1be72b198c98))
* tighten About panel links for repository and version ([#326](https://github.com/the-hcma/bunnify/issues/326)) ([0f1b8ba](https://github.com/the-hcma/bunnify/commit/0f1b8baf7d65ed39cd7f639dc7f453304b870e92))

## [0.7.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.7.0...bunnify-v0.7.1) (2026-08-19)


### Bug Fixes

* Spotty Bunny pipx install flow, About layout, and shared logo ([#323](https://github.com/the-hcma/bunnify/issues/323)) ([68fb2ff](https://github.com/the-hcma/bunnify/commit/68fb2ff2769be8387e064c314a0c3af622abed2d))

## [0.7.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.6.1...bunnify-v0.7.0) (2026-08-18)


### Features

* add macOS dual-Control no-op overlay ([#308](https://github.com/the-hcma/bunnify/issues/308)) ([b8c6cb3](https://github.com/the-hcma/bunnify/commit/b8c6cb33f2a9c02f1dacd6d55a7e6225af52e75c))
* install Spotty Bunny as a login LaunchAgent ([#320](https://github.com/the-hcma/bunnify/issues/320)) ([b7fe2b9](https://github.com/the-hcma/bunnify/commit/b7fe2b904adf182b6d4054bfeae2b7f34f82db61))
* polish Spotty Bunny UI and REPL auto-start ([#316](https://github.com/the-hcma/bunnify/issues/316)) ([753cedf](https://github.com/the-hcma/bunnify/commit/753cedf4d34086beb2cf661af02443fbf290b675))
* resolve Spotty Bunny Enter and open URLs ([#306](https://github.com/the-hcma/bunnify/issues/306)) ([#315](https://github.com/the-hcma/bunnify/issues/315)) ([18205be](https://github.com/the-hcma/bunnify/commit/18205be6b660353548f3240dafc9f15596d780e9))
* reuse Spotty Bunny and server, and add Install to the logo menu ([#322](https://github.com/the-hcma/bunnify/issues/322)) ([25ea51c](https://github.com/the-hcma/bunnify/commit/25ea51c1112737a02ed58be40c45866ff3d0a373))
* share CLI REPL history with Spotty Bunny ([#304](https://github.com/the-hcma/bunnify/issues/304)) ([#311](https://github.com/the-hcma/bunnify/issues/311)) ([bfd3cfc](https://github.com/the-hcma/bunnify/commit/bfd3cfc95890ecb3b2903f2d7259bd2f3bf7648a))
* Spotty Bunny about links, logo menu, and update check ([#321](https://github.com/the-hcma/bunnify/issues/321)) ([349e57c](https://github.com/the-hcma/bunnify/commit/349e57cf59ca52637380cf00d27ba837ac3a748e))
* Tab-complete Spotty Bunny with CLI completers ([#305](https://github.com/the-hcma/bunnify/issues/305)) ([#312](https://github.com/the-hcma/bunnify/issues/312)) ([512a1f4](https://github.com/the-hcma/bunnify/commit/512a1f47ece4dbe636d6ffe6ef9eb0aa11c643ac))


### Bug Fixes

* **deps:** batch updates including CVE fixes ([#318](https://github.com/the-hcma/bunnify/issues/318)) ([26b5e4b](https://github.com/the-hcma/bunnify/commit/26b5e4b24cabfb51b9367f028a5ec8bfec95467d))
* restore Spotty Bunny typing, Esc dismiss, and overlay chrome ([#319](https://github.com/the-hcma/bunnify/issues/319)) ([98a4ef1](https://github.com/the-hcma/bunnify/commit/98a4ef1328fa6c14d85ac081f934b76e4f4ab6d6))
* Spotty Bunny Ctrl-C, dual-Control chord, logging, and rename ([#310](https://github.com/the-hcma/bunnify/issues/310)) ([5625205](https://github.com/the-hcma/bunnify/commit/56252053ebdc44efee462bd652c11ec7221a12cb))
* Spotty Bunny primary display, logo, and about panel ([#317](https://github.com/the-hcma/bunnify/issues/317)) ([d6effe4](https://github.com/the-hcma/bunnify/commit/d6effe48790bf8986f8cb889ccaacbdf51401e27))

## [0.6.1](https://github.com/the-hcma/bunnify/compare/bunnify-v0.6.0...bunnify-v0.6.1) (2026-08-13)


### Bug Fixes

* match REPL Tab completions as contiguous substrings ([#295](https://github.com/the-hcma/bunnify/issues/295)) ([c5d812a](https://github.com/the-hcma/bunnify/commit/c5d812a74441c14e0ef39928459d20c28fa04fbe))

## [0.6.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.5.0...bunnify-v0.6.0) (2026-08-13)


### Features

* add bunnify stop for the managed local server ([#290](https://github.com/the-hcma/bunnify/issues/290)) ([95ca0c2](https://github.com/the-hcma/bunnify/commit/95ca0c21988fd6147cc4a7e8e0fbbfa73eb465c2))
* compare upgrade from/to builds and replace older local servers ([#292](https://github.com/the-hcma/bunnify/issues/292)) ([95c84a8](https://github.com/the-hcma/bunnify/commit/95c84a8061c74fd0583f22ba2f0911ddea81bb52))
* show build identity on setup, REPL, and pipx upgrade ([#289](https://github.com/the-hcma/bunnify/issues/289)) ([a9c6923](https://github.com/the-hcma/bunnify/commit/a9c6923475d0297dc4c739607dbf5a4337e23734))

## [0.5.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.4.0...bunnify-v0.5.0) (2026-08-13)


### Features

* seed example bookmarks during setup and refresh docs ([#284](https://github.com/the-hcma/bunnify/issues/284)) ([36e08b0](https://github.com/the-hcma/bunnify/commit/36e08b0e8488d3c763360227186cd840bc39ce94))


### Bug Fixes

* wait for port free after managed server stop ([#282](https://github.com/the-hcma/bunnify/issues/282)) ([22a1b69](https://github.com/the-hcma/bunnify/commit/22a1b6958b6ef6a5222f6258cd27f8202bd79927))

## [0.4.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.3.0...bunnify-v0.4.0) (2026-08-12)


### Features

* embed release commit and clarify busy-port setup ([#280](https://github.com/the-hcma/bunnify/issues/280)) ([83f279e](https://github.com/the-hcma/bunnify/commit/83f279eeff5c3b976815893296b224b3c7e1a606))

## [0.3.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.2.0...bunnify-v0.3.0) (2026-08-12)


### Features

* bunnify onboard + PyPI next-step docs ([#277](https://github.com/the-hcma/bunnify/issues/277)) ([dca2a1f](https://github.com/the-hcma/bunnify/commit/dca2a1fbac6a46208e9dcf05e471bc1460b2d991))
* web UI version under logo + Edge/bunnylol welcome ([#279](https://github.com/the-hcma/bunnify/issues/279)) ([dfd2fc1](https://github.com/the-hcma/bunnify/commit/dfd2fc1f58082b188f6cbe4c3024eea069cf8fd5))

## [0.2.0](https://github.com/the-hcma/bunnify/compare/bunnify-v0.1.1...bunnify-v0.2.0) (2026-08-12)


### Features

* local/remote setup with health verification ([#264](https://github.com/the-hcma/bunnify/issues/264)) ([#267](https://github.com/the-hcma/bunnify/issues/267)) ([4789548](https://github.com/the-hcma/bunnify/commit/47895483faf141fd8de1d93ba56caf589c12e55d))
* pipx-ready bunnify-server and packaging smoke ([#263](https://github.com/the-hcma/bunnify/issues/263)) ([#268](https://github.com/the-hcma/bunnify/issues/268)) ([85ea7df](https://github.com/the-hcma/bunnify/commit/85ea7df91a605dc0ef18fe39e19ec7de03e507df))
* XDG config for bookmarks and settings ([#261](https://github.com/the-hcma/bunnify/issues/261)) ([#266](https://github.com/the-hcma/bunnify/issues/266)) ([1f8fce6](https://github.com/the-hcma/bunnify/commit/1f8fce637900fbb1d37841d44a115064ba4fe3b9))


### Bug Fixes

* restore systemd startup after pipx packaging ([#271](https://github.com/the-hcma/bunnify/issues/271)) ([5e25c00](https://github.com/the-hcma/bunnify/commit/5e25c00db9cf9b39ea5380631cd8fda37a062d22))
* use @.name.value jsonpath so Release Please bumps uv.lock ([#270](https://github.com/the-hcma/bunnify/issues/270)) ([5239ef6](https://github.com/the-hcma/bunnify/commit/5239ef6f34877a41c58b37b82fd69dab3aa95e87))


### Documentation

* modernize install and usage for pipx and XDG ([#265](https://github.com/the-hcma/bunnify/issues/265)) ([#272](https://github.com/the-hcma/bunnify/issues/272)) ([c613b63](https://github.com/the-hcma/bunnify/commit/c613b631911725431d93959431e79935d5161982))
