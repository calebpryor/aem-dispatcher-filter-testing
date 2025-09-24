## Dispatcher Filter Testing Directory

### Filter Files
You should name all the files you put in this directory that you want included in the running image as `<UNIQUENAME>_filters.any`

If you number them like:
```
000_firstfile_filters.any
002_secondfile_filters.any
etc..
```
Then it will load them in that order.

### Filter Test Log
When the container is running, filter-related log entries are automatically extracted to:
- **`filter-test.log`** - Contains filtered dispatcher log entries showing:
  - Filter rule evaluations (`Filter rule entry`)
  - Request allowed/blocked decisions
  - URL decomposition details (method, uri, path, extension, selectors, suffix, query)
  - Filter rejection messages

This log file is continuously updated as requests are processed by the dispatcher. It provides a focused view of filter behavior without the noise of other dispatcher operations.