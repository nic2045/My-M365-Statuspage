# Changelog

## [1.4.0](https://github.com/nic2045/My-M365-Statuspage/compare/v1.3.0...v1.4.0) (2026-05-17)


### Features

* /admin/incidents page, service filters, dashboard polish ([dc87b62](https://github.com/nic2045/My-M365-Statuspage/commit/dc87b6259cfa42b96517bfdc106f2ab779cf5bd7), [6bc562e](https://github.com/nic2045/My-M365-Statuspage/commit/6bc562e824c40fee8b4bf189aeec3f04b5c50628))
* Azure AD settings UI, connection verify on save, history card polish ([cff0246](https://github.com/nic2045/My-M365-Statuspage/commit/cff0246b5874768d77a60191aae18258de8ae18a), [de42dd3](https://github.com/nic2045/My-M365-Statuspage/commit/de42dd3feced97ba08e3bbdf71db9aedeb9b0bcf))
* click-through from day modal + service filter on history ([802b906](https://github.com/nic2045/My-M365-Statuspage/commit/802b9062492f40437c97fab7e9784079c4096cd2), [13e068b](https://github.com/nic2045/My-M365-Statuspage/commit/13e068b87a1cd6d4dbea7287a0ba373e580a8456))
* click-to-detail overlay on uptime bars + incident cards ([0355b65](https://github.com/nic2045/My-M365-Statuspage/commit/0355b65a6cf98c58dd519f4324a3d41c4a85fdaa)), closes [#52](https://github.com/nic2045/My-M365-Statuspage/issues/52)
* dashboard redesign + click-to-detail overlay + split incidents/advisories ([1c36bdf](https://github.com/nic2045/My-M365-Statuspage/commit/1c36bdf974a57943d9cc713383596c83d74bdb33))
* email settings UI with SMTP password + MS Graph OAuth2 support ([29542c6](https://github.com/nic2045/My-M365-Statuspage/commit/29542c6cec20dbc78c1ff766a8cba5b80e925bb5), [d4fdc34](https://github.com/nic2045/My-M365-Statuspage/commit/d4fdc346b3aa153e20a4439b88d05d32bc868c98)), closes [#35](https://github.com/nic2045/My-M365-Statuspage/issues/35)
* filter dropdowns, source/ref on incidents, tab nav UX, badge sizes ([abc0ea6](https://github.com/nic2045/My-M365-Statuspage/commit/abc0ea6bc8b59a2c8ec6361fc62cd5efeeae7be9), [d34ead0](https://github.com/nic2045/My-M365-Statuspage/commit/d34ead038844344c3ffb6ccf13670f7ac341321d))
* modern-look bundle — toasts, pulse, empty states, color audit ([415a88c](https://github.com/nic2045/My-M365-Statuspage/commit/415a88c7121e415f926c9f067c80d47eb6e81838), [11ab687](https://github.com/nic2045/My-M365-Statuspage/commit/11ab687fa640f8cc751f48e047909018cdd813f4))
* public page split (incidents/advisories) + bar hover tooltip + debug timeline ([d109004](https://github.com/nic2045/My-M365-Statuspage/commit/d109004522be24aa5bf48abbc230c0152560b4ab), [9252501](https://github.com/nic2045/My-M365-Statuspage/commit/92525015e621f985ea3fb605f1fe734763d7ea9a))
* PWA support (manifest, service worker, install prompt) ([faa5990](https://github.com/nic2045/My-M365-Statuspage/commit/faa5990a0710661140e5694abc781e6b1add63c9), [7787e1b](https://github.com/nic2045/My-M365-Statuspage/commit/7787e1b808193aaf3868d4e2ce63e3cc801aa111)), closes [#52](https://github.com/nic2045/My-M365-Statuspage/issues/52)
* restore advisories section on admin dashboard ([4fa33c6](https://github.com/nic2045/My-M365-Statuspage/commit/4fa33c64b4d3d20f4dc0e48030cfb5e3672c48a0), [fa4525d](https://github.com/nic2045/My-M365-Statuspage/commit/fa4525de99dc80ba54a6c12fdd3fba95eb694861))
* sortable service order via admin (up/down arrows) ([6e7c193](https://github.com/nic2045/My-M365-Statuspage/commit/6e7c1939cdd06a8f8f05403c48e0fe791ad4b047), [917b9db](https://github.com/nic2045/My-M365-Statuspage/commit/917b9dbe1f992c0e9035d0be2f9149830603cc83))
* top tab nav with subscribe modal, sidebar back-to-public, drop dashboard advisories ([97fe22e](https://github.com/nic2045/My-M365-Statuspage/commit/97fe22e3f3bff13f427aa4910ad840275b855de8), [1cd3290](https://github.com/nic2045/My-M365-Statuspage/commit/1cd32900e60bd6cc416dd0ee4a4b9e82b4651063), [0fd7a70](https://github.com/nic2045/My-M365-Statuspage/commit/0fd7a709d58ea8ec6ef76d6d7ae82cea7b3fb9f3))


### Bug Fixes

* dashboard redesign, split incidents/advisories, repair 500s ([5bdbff9](https://github.com/nic2045/My-M365-Statuspage/commit/5bdbff9bc8fa3c6f2ce6ec0eea5885391491ee7b)), closes [#52](https://github.com/nic2045/My-M365-Statuspage/issues/52)

## [1.3.0](https://github.com/nic2045/My-M365-Statuspage/compare/v1.2.0...v1.3.0) (2026-05-17)


### Features

* service groups on status page ([5ec3eab](https://github.com/nic2045/My-M365-Statuspage/commit/5ec3eab4e6bb8893e847654142934e0741ad5c3f)), closes [#36](https://github.com/nic2045/My-M365-Statuspage/issues/36)
* subscriber notifications (Email + MS Teams) ([a543bd1](https://github.com/nic2045/My-M365-Statuspage/commit/a543bd1d8cc68b2df3bf2b3c44252a8a6e947727)), closes [#35](https://github.com/nic2045/My-M365-Statuspage/issues/35)
* subscriber notifications (Email + MS Teams) [#35](https://github.com/nic2045/My-M365-Statuspage/issues/35) ([a2091fd](https://github.com/nic2045/My-M365-Statuspage/commit/a2091fd56e3db2985a20e549c5122b31acee22e6))


### Bug Fixes

* sort imports and remove unused import (ruff) ([d58c893](https://github.com/nic2045/My-M365-Statuspage/commit/d58c893edd9f34d8a126c9ebb1e5eb220aa341b5))

## [1.2.0](https://github.com/nic2045/My-M365-Statuspage/compare/v1.1.1...v1.2.0) (2026-05-17)


### Features

* admin sidebar navigation with live counters ([21e778e](https://github.com/nic2045/My-M365-Statuspage/commit/21e778ee9f369a6e99d9bc11cec08a1b19be78a6)), closes [#40](https://github.com/nic2045/My-M365-Statuspage/issues/40)
* advisory + planForChange + maintenance in_progress ([be2907a](https://github.com/nic2045/My-M365-Statuspage/commit/be2907a73d4c60690540eb576611aa4d549a9b98))
* compute uptime bars live from incidents ([cc53384](https://github.com/nic2045/My-M365-Statuspage/commit/cc53384e7a15f081729f40d7856820240d9ce2b6))
* incident form polish, phase visualization, delete ([ab5bd00](https://github.com/nic2045/My-M365-Statuspage/commit/ab5bd00754ef2a1a1ced15315d6ae2e2a97bdd4e))
* map Graph issue status to incident phases ([9ed0ae1](https://github.com/nic2045/My-M365-Statuspage/commit/9ed0ae14f50c6d1e88175b52171590a62483e178))

## [1.1.1](https://github.com/nic2045/My-M365-Statuspage/compare/v1.1.0...v1.1.1) (2026-05-17)


### Bug Fixes

* backfill OData filter, uptime % position, version visibility ([6c48771](https://github.com/nic2045/My-M365-Statuspage/commit/6c48771da7ab1ed7fe1d235718b4976155ad9505))

## [1.1.0](https://github.com/nic2045/My-M365-Statuspage/compare/v1.0.0...v1.1.0) (2026-05-17)


### Features

* add end_datetime to incidents (actual resolution time) ([8f6b998](https://github.com/nic2045/My-M365-Statuspage/commit/8f6b99843cba729e2651375ca20953080d8fb58b))
* admin service management, brand color update, container rename ([0e8cbab](https://github.com/nic2045/My-M365-Statuspage/commit/0e8cbab590cd0a1dd25e074532f4e6578345c697))
* admin service management, brand colors & container rename ([ef93776](https://github.com/nic2045/My-M365-Statuspage/commit/ef9377643453cc9383315a77e547b0f4fd1c4e09))
* admin sidebar layout with Einstellungen and Debug tabs ([d4f8b4a](https://github.com/nic2045/My-M365-Statuspage/commit/d4f8b4a3e727474717f679dc3ed3f2334b056957))
* admin sidebar with Einstellungen, Debug tabs and service management page ([208e39c](https://github.com/nic2045/My-M365-Statuspage/commit/208e39c46d3509bb63f69790152ab69923dd35f4))
* delayed Graph API poll after enabling a service ([90bedc6](https://github.com/nic2045/My-M365-Statuspage/commit/90bedc67f2ab46047b07e8c8b99fee429a1ef675))
* delayed Graph API poll after enabling a service ([b3bce44](https://github.com/nic2045/My-M365-Statuspage/commit/b3bce448f5d7157086eb5fa2f54ec328fb01cb6d))
* filter Graph API issues by classification (incident/maintenance only) ([0fbe08c](https://github.com/nic2045/My-M365-Statuspage/commit/0fbe08c1f361cc200504274f81efa439c38e1b41))
* filter Graph issues by classification — incident/maintenance only, skip advisory ([59d21c8](https://github.com/nic2045/My-M365-Statuspage/commit/59d21c8f6ef1a3c7b99b94fa072ea882f98114de))
* incident end_datetime – actual resolution time field ([b9aa4b7](https://github.com/nic2045/My-M365-Statuspage/commit/b9aa4b7346e3604630f1373b00ea3039bafd9bf7))
* incident history section on public page + resolved issue sync ([9d3f661](https://github.com/nic2045/My-M365-Statuspage/commit/9d3f661c60a8e34ed211e1718a466b2f6e3c9f3f))
* Verfügbarkeits-Toggle, Versions-Anzeige & Release Please ([d2508f4](https://github.com/nic2045/My-M365-Statuspage/commit/d2508f40b5790071dca58f7d1c15915dd20b4daf))


### Bug Fixes

* **admin:** keep sidebar on detail pages, drop resolved list, show severity in suppressed ([aa87bce](https://github.com/nic2045/My-M365-Statuspage/commit/aa87bced56f2d3c9f9b74209fb9cd3de35b04c40))
* **admin:** keep sidebar on detail/forms, drop resolved-list, show severity in suppressed ([d4e1415](https://github.com/nic2045/My-M365-Statuspage/commit/d4e14156d59b1645027fbaf4acddd4c923b5fda0))
* fetch issue posts per-resource instead of $expand on collection ([8d15183](https://github.com/nic2045/My-M365-Statuspage/commit/8d15183dda3bc41b97275169f6cfd10140e2a007))
* incident message display + debounced delayed poll ([016fb30](https://github.com/nic2045/My-M365-Statuspage/commit/016fb303e0dddaa160c91359016874986d1a7501))
* isolate incident phases + debounce delayed poll ([a8fbb39](https://github.com/nic2045/My-M365-Statuspage/commit/a8fbb3929e59f1b2e0b92d32177208ef44a1ce76))
* remove inline import in update_incident route ([e4f5ca1](https://github.com/nic2045/My-M365-Statuspage/commit/e4f5ca1f83f06c49a91ad8dd4a130e565b00f3f0))
* resolve Graph API 400 errors by fetching issue posts per-resource ([fcd8fc9](https://github.com/nic2045/My-M365-Statuspage/commit/fcd8fc994b51241878a1546a59bdce3c1a261d57))
* use startDateTime filter for resolved issues (lastModifiedDateTime not filterable) ([7da0590](https://github.com/nic2045/My-M365-Statuspage/commit/7da05907387e3a0aef4bef4c43959e83634d2258))
