# Store migrations

`<n>.sql` carries a format n-1 store to format n (src/bitt/storeformat.py; AGENTS.md "Changing the store's shape"). Applied in order, in one
transaction, by `bitt migrate`. None yet: format 1 is v2.0.1's store.
