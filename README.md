# Dual-Photo-editor

When the application starts you will be prompted to choose an input
directory that contains two sub-folders named `FULL` and `PARTIAL` with
matching file names. The editor now keeps all modified images inside an
automatically managed `EDITED` directory alongside your originals. The
structure that will be created looks like this:

```
<selected folder>/
├── FULL/
├── PARTIAL/
└── EDITED/
    ├── FULL/
    └── PARTIAL/
```

The original files in `FULL` and `PARTIAL` remain untouched. Every time
you load a pair the program copies them (if needed) into the `EDITED`
folders and all subsequent saves update those copies. Opening the
`EDITED` folder after saving will therefore show the latest changes made
in the editor.
