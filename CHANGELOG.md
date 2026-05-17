# Changelog

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
