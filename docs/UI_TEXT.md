# KidneyCyst — UI copy

**How to edit**
- One item per line: `label` then the text. **Change only the text after the label.** Keep the label so I can put your version back in the right place.
- To remove an item, write `(remove)` as its text. To add something, add a new line with a label like `home.new1` and say where it goes.
- `{n}`, `{date}` etc. are filled in by the app: keep them (or move them) but don't rename them.
- Keyboard keys are shown like `[A]`.
- Things marked *(tooltip)* appear only when the mouse rests on a button.
- Lengths: buttons should stay short (1–4 words) or they wrap.

---

## 1. Start page

### Header
`home.title` KidneyCyst
`home.lede` Pronephros segmentation and area measurement in GFP images of zebrafish larvae.
`home.help` Help
`start.busy` Detection running: {run name} · {i} of {n} images [· on {host}]  `View`

### New analysis
`start.new.heading` New analysis
`start.new.choose` Choose image folder…
`start.new.or` or paste a folder path
`start.new.placeholder` e.g. D:\Opera\Run5\Plate1
`start.new.open` Open
`start.new.hint` TIFF images (.tif, .tiff) with GFP in the first channel, subfolders included. If the folder was analysed before, that run opens.
`home.import.err.none` No TIFF images found in this folder or its subfolders. Select a folder containing .tif or .tiff images.
`home.import.err.notfolder` The path is not a folder: {path}
`start.err.busy` A detection is running. Choose another folder after it finishes, or cancel it on its run page.

### Your runs
`start.runs.heading` Your runs
`start.runs.search` Search name, folder or status *(placeholder; shown from 4 runs on)*
`start.runs.add` Open existing results…
`start.runs.scan` Find results in a folder… *(tooltip: Add every results folder found inside a folder, for example after reinstalling)*
`start.runs.cols` Name · Date · Images · Reviewed · Median area · Status
`start.runs.open` Open
`start.runs.more` ⋯ *(tooltip: Report, snapshots, rename, remove)*
`start.runs.more.text` Open its report, see the saved report copies, rename the run, or remove it from this list. Removing does not delete any files.
`start.runs.more.buttons` Cancel · Remove from list · Rename · Report copies ({n}) · Open report
`start.runs.empty` No runs yet. Choose an image folder above to start, or open results you already have.
`start.runs.missing` Folder not found (moved, renamed or on a drive that is not connected).  `Locate…` · `Remove from list`
`start.runs.note` Runs known to this installation: {folder}. Removing a run from the list never deletes its files.
`start.status` Not detected yet · Detected · In review · Final · Cancelled
`home.earlier.err` No KidneyCyst results found. Select a results folder ending in _kidneycyst.

---

## 1b. Run page (one run)

### Header
`run.back` ‹ All runs
`run.rename` Rename *(also: click the name)*
`run.facts` {n} images · detected {date} · {model} · {device or "on {host}"}
`run.facts.new` {n} TIFF images · not detected yet
`run.images` Images: {folder}
`run.images.missing` Image folder not found (moved or on a drive that is not connected). Review and results still work.
`run.details` Details → Results folder: {folder}. Detection took {time}.
`run.other.text` Another run ({name}) was opened in a different tab. This page is paused so nothing is saved to the wrong run.
`run.other.back` Switch back to {this run}
`run.other.go` Go to {other run}
`run.busy` A detection for another run is in progress. Start this one after it finishes.
`run.step.locked` Available after detection. *(Results adds: The report and Excel table update after every review decision.)*

### Step 1: Detect kidney outlines
`home.detect.heading` Detect kidney outlines
`home.detect.run` Run detection
`home.detect.fast` Fast mode (1 model instead of 3)
`home.detect.device.nvidia` Processing device: NVIDIA GPU ({name}).
`home.detect.device.apple` Processing device: Apple GPU.
`home.detect.device.cpu` Processing device: CPU. Processing may be slower than on a supported GPU.
`home.detect.cancel` Cancel
`home.detect.loading` Loading model…
`home.detect.loading.sub` Elapsed: {time}. Initial loading may take longer.
`home.detect.progress` Processed {i} of {n} images. Last image: {image}
`home.detect.left` Estimated time remaining: {time}
`home.detect.writing` Saving results and generating report…
`home.detect.finished` Detection complete. Duration: {time}.
`home.detect.cancelled` Detection cancelled. Processed {i} of {n} images.
`home.detect.stopping` Stopping after the current image…
`home.detect.stopped` Detection stopped.
`home.detect.error` Detection failed. {error} See Details for diagnostic information.
`home.detect.details` Processing details
`home.detect.done` {n} images detected on {date}.
`home.detect.done.cancelled` Partial results: {n} images, {date}. Detection was cancelled.
`home.detect.again` Run again…
`home.detect.where.here` (shown above the Run detection button, after Model and Pixel size) {device line above}  `Change where detection runs`
`home.detect.where.remote` Detection runs on {host} ({graphics card}).  `Change where detection runs`
`run.model.label` Model
`run.model.kc009` KC009: 3 models, accuracy measured (recommended)
`run.model.kc014` KC014: one all-data model, trained on data v1, no measured accuracy [(not in this installation)]
`run.model.kc014.note` KC014 was trained on all 686 data-v1 images (Run2-4, Nov 2026 outlines); no held-out score exists; use KC009 folds for measured accuracy. Results record which model was used.
`report.toolbar.review` Review outlines
`report.viewer` Well {well}, field {f} — {image id} · {plate} — Input · Outline (model) / Outline (corrected) / No outline — Current area · Model area · Review decision · Flags [· Grade (beta) · Elbow (beta) · Grade (yours) · Elbow measured] — `‹ Previous` {i} of {n} `Next ›` — `Edit this image`
`report.thumb.tooltip` Open larger *(tooltip on every thumbnail and plate-map image)*
`report.platemap.sub` Median kidney area per well. Click a well to see its images and numbers on the right.
`report.platemap.empty` Click a well to see its images and measurements here.
`report.platemap.detail` Well {well} · {plate} — {n} images · {median} median µm² · {r}/{n} reviewed — per image: Field {f} · {area} µm², decision, flags — `Show in the table`
`home.detect.where.slurm` Detection runs as a job on {host} (partition {partition}).  `Change where detection runs`
`home.detect.queued` Waiting for a GPU on {host} (job {id}: {reason}). *(reasons: other jobs are ahead in the queue · waiting for a free GPU · you already have the maximum number of jobs running · the requested GPU nodes are unavailable)*
`home.detect.queued.sub` Elapsed: {time}. Cancelling now withdraws the job.
`home.detect.queued.cancelled` Detection cancelled before the job started.
`home.detect.job.failed` Job {id} on {host} ended before detection finished (it may have run out of time or memory, or been cancelled). Last lines: {lines}
`home.detect.job.refused` The job queue on {host} refused the job: {reason}. Check the job options under 'Change where detection runs'.
`home.detect.copy.up` Copying images to {host}: {done} of {total} MB.
`home.detect.copy.down` Copying results back from {host}: {n} MB.
`home.detect.remote.start` Starting KidneyCyst on {host} and loading the model…
`home.detect.remote.progress` Processed {i} of {n} images on {host}. Last image: {image}
`home.detect.remote.failed.title` Detection on {host} did not finish
`home.detect.remote.failed.text` {error} Run detection on this computer instead? It is slower without a graphics card.  `Not now` · `Run on this computer`

### Dialog: Where detection runs
`gpu.title` Where detection runs
`gpu.here` This computer — {device}
`gpu.remote` Another computer, over SSH — For a computer with a graphics card that you can log in to. Images are copied there for detection; review, report and files stay here.
`gpu.host` Computer name or address *(placeholder: for example gpu-box or name@10.1.2.3)*
`gpu.cmd` Advanced: command that starts KidneyCyst there *(placeholder: found automatically)*
`gpu.test` Test connection
`gpu.key` Set up key login…
`gpu.ok.connected` Connected to {host} ({s} s).
`gpu.ok.found` KidneyCyst {version} found.
`gpu.ok.model` Model: {model}.
`gpu.ok.gpu` Graphics card: {name}.
`gpu.warn.cpu` {host} has no usable graphics card: detection there runs on its CPU.
`gpu.warn.model` This computer has a different model ({model}). Results will come from the other computer's model; the report records which.
`gpu.err.key` {host} refused the login without a password. The app can only use key login. Click 'Set up key login' (you type your password once).
`gpu.err.name` The name {host} is unknown to this computer. Check the spelling, or use its address (for example 10.1.2.3).
`gpu.err.unreachable` {host} cannot be reached. Check the VPN or network connection, and that the computer is on.
`gpu.err.notfound` KidneyCyst is not installed on {host} (the usual places, your home folder and conda environments were searched).
`gpu.install.hint` Click 'Install KidneyCyst there' and the app sets it up for you: it copies the program and model from this computer and downloads Python and PyTorch there (about 10 minutes, 8 GB in your home folder there). If KidneyCyst is already installed there in another place, open Advanced and enter the command that starts it instead.
`gpu.err.badcmd` The command '{command}' did not start KidneyCyst on {host}. Check it under Advanced, or clear it to search automatically.
`gpu.install.btn` Install KidneyCyst there   (after a failure: Try the installation again)
`gpu.install.confirm` Install KidneyCyst on {host}? — The app copies the program and model from this computer to a new folder ~/KidneyCyst-remote in your home folder there, and downloads Python and PyTorch there. It takes about 10 minutes and needs about 8 GB there. Nothing else on that computer is changed.  [Cancel] [Install]
`gpu.install.steps` Checking the other computer… / Copying the program and model to {host}… / Downloading the installer tool… / Creating a Python environment… / Downloading and installing PyTorch (the largest step)… / Installing KidneyCyst… / Checking the installation… / Installed. Testing the connection again…
`gpu.install.done` KidneyCyst is installed on {host}. Click Save to use it.
`gpu.install.bg` You can close this window; the installation carries on. Open it again to see how far it is.
`gpu.install.err.space` Your home folder on {host} has only {n} GB free; the installation needs about 8 GB.
`gpu.install.err.other` {host} already has a folder ~/KidneyCyst-remote that was not made by KidneyCyst. Rename or remove it there, then try again.
`gpu.install.err.stopped` Installing on {host} stopped during: {step} (does it have internet access?). Last line: {line}
`gpu.err.nossh` No SSH program found on this computer. On Windows 10/11 add "OpenSSH Client" under Settings › Apps › Optional features.
`gpu.key.opened` A terminal window opened. Type your password there once, then click Test connection again.
`gpu.slurm.found` Job queue (Slurm) found: detection runs as a job on a GPU node, not on {host} itself. Partitions with GPUs: {list}.
`gpu.slurm.nogpu` {host} has a job queue (Slurm) but no partition with GPUs was found.
`gpu.slurm.options` Job options (Slurm) *(prefilled, e.g. --partition=gpuq --gres=gpu:1 --time=02:00:00 --mem=32G --cpus-per-task=4)*
`gpu.slurm.hint` Detection is submitted as a job and starts when a GPU is free. Change the partition or time limit here if your cluster needs it.
`gpu.slurm.badopt` Job option not accepted: {option}. Use options like --partition=gpuq --gres=gpu:1 --time=02:00:00.
`gpu.cancel` Cancel · `gpu.save` Save *(Save is enabled after a successful test)*

### Step 2: Review outlines
`home.check.heading` Review outlines
`home.check.n` images
`home.check.withoutline` with an outline
`home.check.checked` reviewed
`home.check.todo` unreviewed
`home.check.median` median area
`home.check.median.unchecked` median area — {k} images, {n} not yet reviewed
`home.check.median.allchecked` median area — {k} images, all reviewed
`home.check.review` Review outlines
`home.check.continue` Resume review ({n} left)
`home.check.again` Review again
`home.check.calib.tiff` (removed: shown in the report and Excel instead)
`home.check.calib.assumed` Unverified calibration: {px} µm/pixel. TIFF metadata is missing; areas in µm² use this default.

### Step 3: Results
`home.export.heading` Results
`home.export.report` Open report
`home.export.table` Open Excel table
`home.export.folder` Open results folder
`home.export.qupath.label` QuPath *(folded section, with a small 'optional' tag)*
`home.export.qupath.text` Open the outlines in QuPath, edit them there, then import the edits back into KidneyCyst.
`home.export.qupath.tag` optional
`home.export.qupath.open` Open in QuPath
`home.export.qupath.sync` Import QuPath edits

### Pop-ups on the run page
`home.modal.rerun.title` Run detection again?
`home.modal.rerun.text` This run has reviewed results. A new run will archive the existing results in a replaced_… folder. Previous review decisions will not be included in the new results.
`home.modal.rerun.no` Keep current results
`home.modal.rerun.yes` Run again
`home.modal.cancel.title` Cancel detection?
`home.modal.cancel.text` Completed results will be retained and available for review.
`home.modal.cancel.no` Keep running
`home.modal.cancel.yes` Cancel detection
`home.modal.qpsupport.title` Install QuPath integration?
`home.modal.qpsupport.text` Download and install paquo and JPype (approximately 30 MB) to exchange outlines with QuPath. [if QuPath is missing:] QuPath 0.6.0 will also be downloaded (approximately 260 MB). An internet connection is required. You can review outlines in KidneyCyst without installing these components.
`home.modal.qpsupport.no` Not now
`home.modal.qpsupport.yes` Install integration
`home.modal.qpsupport.busy` Installing QuPath integration…
`home.modal.qpdownload.title` QuPath is not installed
`home.modal.qpdownload.text` Download QuPath 0.6.0 (approximately 260 MB). An internet connection is required.
`home.modal.qpdownload.no` Not now
`home.modal.qpdownload.yes` Download QuPath
`home.modal.qpdownload.busy` Downloading QuPath…
---

## 2. Review screen

### Top bar
`rv.top.home` ‹ {run name} *(back to the run page)*
`rv.top.home.tooltip` Return to home *(tooltip)*
`rv.top.title` Well {well}, field {field}
`rv.top.done` {d} of {n} reviewed
`rv.top.report` Open report
`rv.top.help` Help
`rv.top.help.tooltip` Help (opens in a new tab) *(tooltip)*
`rv.top.empty` No results available. Run detection to begin review.

### Image list (left)
`rv.list.filter.todo` Unreviewed
`rv.list.filter.flagged` Flagged images
`rv.list.filter.all` All images
`rv.list.item` {well}, field {field}
`rv.list.noarea` —
`rv.list.legend.unchecked` unreviewed
`rv.list.legend.flagged` flagged
`rv.list.legend.right` accepted
`rv.list.legend.corrected` corrected
`rv.list.legend.nokidney` no kidney
`rv.list.legend.cannot` cannot assess

### On the image
`rv.legend.model` Model outline
`rv.legend.yours` Your outline (after editing)
`rv.legend.before` Model outline before your edits *(dashed)*
`rv.scale` {n} µm
`rv.zoom` {n}%

### Right panel: state
`rv.flag` Model flags: {flags}
`rv.state.auto` Unreviewed
`rv.state.accepted` Reviewed · Outline accepted
`rv.state.edited` Reviewed · Outline corrected
`rv.state.deleted` Reviewed · No kidney visible
`rv.state.unusable` Reviewed · Cannot assess
`rv.state.dirty` Unsaved changes
`rv.area.model` Model area
`rv.area.now` Current area
`rv.area.none` No outline
`rv.area.diff` {+n}% relative to model area

### Right panel: Grade & elbow (beta, below the decision buttons)
`rv.beta.heading` Grade & elbow  `beta` *(tooltip: Not yet validated against manual grading and elbow measurements)*
`rv.beta.model.grade` Model grade — {grade} {p}% [· uncertain] / not available
`rv.beta.model.elbow` Model elbow — {n} µm straight · {m} midline
`rv.beta.your.grade` Your grade — not set / normal / unfused / cyst
`rv.beta.your.elbow` Your elbow — {n} µm path · {m} straight / not measured
`rv.beta.measure` Measure elbow `[M]`
`rv.beta.clear` Clear
`rv.beta.tip` Click along the tubule from one elbow to the other. Double-click or [Enter] to finish; [Esc] or [Z] removes the last point.
`rv.beta.toast.measured` Elbow measured: {n} µm along the tubule.
`rv.beta.toast.cleared` Elbow measurement removed.
`rv.beta.toast.grade` Your grade saved: {grade}. / Your grade removed.
`rv.beta.toast.twopoints` Click at least two points along the tubule.
`rv.view.elbowlines` Elbow lines shown / Elbow lines hidden `[J]`
`rv.legend.elbow.model` Model elbow (beta) *(dotted orange)*
`rv.legend.elbow.yours` Your elbow *(blue with dots)*
`report.beta.note` Grade and elbow (beta): computed from the model outline, not yet validated against manual grading and elbow measurements. The grade shows its probability; "?" marks a grade below the confidence threshold. "Yours" columns are measurements made in the review screen.
`report.cols.beta` Grade (beta) · Elbow µm (beta) · Grade (yours) · Elbow measured µm
`xlsx.cols.beta` Grade (beta) · Grade probability (beta) · Elbow straight µm (beta) · Elbow midline µm (beta) · Grade (yours) · Elbow measured straight µm · Elbow measured path µm · Elbow measured by

### Right panel: decisions
`rv.btn.accept` Accept & next `[A]`
`rv.btn.save` Save & next `[A]` *(shown instead when you changed the outline)*
`rv.btn.acceptnone` No kidney & next `[A]` *(shown when the model found nothing)*
`rv.btn.nokidney` No kidney visible `[N]`
`rv.btn.nokidney.tooltip` Record that no kidney is visible in this image *(tooltip)*
`rv.btn.cannot` Cannot assess `[C]`
`rv.btn.cannot.tooltip` Mark the image as unassessable and exclude its area from summary statistics *(tooltip)*
`rv.btn.prev` Previous `[←]`
`rv.btn.skip` Skip `[→]`
`rv.btn.skip.tooltip` Skip this image without recording a review decision *(tooltip)*

### Right panel: Tool (one active at a time; Pan is the start mode)
`rv.tool.heading` Tool
`rv.tool.pan` Pan `[P]` *(tooltip: Drag to move the image. Scroll to zoom.)*
`rv.tool.brush` Brush `[B]` *(tooltip: Paint to add to the outline)*
`rv.tool.eraser` Eraser `[E]` *(tooltip: Paint to remove from the outline)*
`rv.tool.lasso` Lasso `[L]` *(tooltip: Draw around a region to add it)*
`rv.tool.cut` Lasso cut `[K]` *(tooltip: Draw around a region to remove it)*
`rv.tool.size` Brush size `[ ]` *(shown only for Brush and Eraser)*
`rv.tool.size.value` {n} px

### Right panel: Edit
`rv.edit.heading` Edit
`rv.edit.undo` Undo `[Z]`
`rv.edit.redo` Redo `[Y]`
`rv.edit.restore` Restore model outline `[R]`

### Right panel: View
`rv.view.heading` View
`rv.view.fit` Fit outline `[F]`
`rv.view.whole` Fit image `[W]`
`rv.view.outlines.on` Outlines shown `[O]`
`rv.view.outlines.off` Outlines hidden `[O]`
`rv.view.original` Hide Annotations `[H]` (hold)
`rv.view.fill` Fill opacity
`rv.keys.button` Keyboard shortcuts `[?]`
`rv.split.tooltip` Drag to change the width *(tooltip on the two panel edges; double-click resets)*

### Keyboard shortcuts dialog
`rv.keys.title` Keyboard shortcuts
`rv.keys.decide` Decide: `[A]`/`[Enter]` accept or save edits, then advance · `[N]` no kidney visible · `[C]` cannot assess · `[→]` `[←]` skip / previous image
`rv.keys.tool` Tool: `[P]` pan (start mode; scroll to zoom) · `[B]` `[E]` brush / eraser · `[L]` `[K]` lasso / lasso cut · `[` `]` smaller / larger brush
`rv.keys.edit` Edit: `[Z]` `[Y]` `[R]` undo / redo / restore model outline
`rv.keys.view` View: `[F]` `[W]` fit outline / fit image · `[O]` outlines on or off · hold `[H]` hide annotations · hold `[Space]` pan with any tool
`rv.keys.close` Close

### Messages on the review screen
`rv.toast.accepted` Outline accepted.
`rv.toast.edited` Outline saved.
`rv.toast.deleted` Marked as no kidney visible.
`rv.toast.unusable` Marked as cannot assess.
`rv.toast.undo` Undo `[U]` *(button in the message, shown for 8 s after every saved decision)*
`rv.toast.undone` Decision undone.
`rv.keys.undo` `[U]` Undo the last saved decision
`rv.modal.unsaved.title` Save changes to well {well}, field {field}?
`rv.modal.unsaved.text` This outline has unsaved changes.
`rv.modal.unsaved.keep` Keep editing
`rv.modal.unsaved.discard` Discard changes
`rv.modal.unsaved.save` Save & continue
`rv.modal.done.title` Review complete for this list
`rv.modal.done.some` Unreviewed images remain in other lists. Change the filter to continue.
`rv.modal.done.all` All images have been reviewed. The results table and report are up to date. *(OK returns to the run page)*
`rv.modal.notsaved.title` Could not save outline
`rv.modal.notsaved.text` {error} Your edits remain on screen. Retry saving before leaving this image.

---

## 3. Help (separate page, menu on the left)

`help.back` Back to KidneyCyst
`help.menu` Quick start · Model & validation · How to cite · Licenses & acknowledgments · Data & network · Report a problem · About

### Quick start
`help.start.title` Quick start
`help.start.1` Import images. Select a folder containing 2-D TIFF images or z-projections, with GFP in the first channel. Subfolders are included.
`help.start.2` Run detection. KidneyCyst generates candidate pronephros outlines and calculates their areas in µm² using the recorded pixel size.
`help.start.3` Review outlines. Accept an outline with A, mark no kidney visible with N, or mark an image as unassessable with C. Use the brush or lasso to edit an outline, then press A to save and advance.
`help.start.4` Open results. The Excel table and report are updated after each review decision. Select Open Excel table to view the measurements.
`help.start.results` Results are saved beside the input folder in <your folder>_kidneycyst. Source images are not modified.
`help.start.speed` Processing time depends on the device and image size. Fast mode uses one model instead of the three-model ensemble.
`help.start.names` Sample identifiers are extracted from Opera/Harmony filenames, such as … Well B07, Field 4.tif. Folder names containing Run5 or Plate2 provide run and plate identifiers.
`help.start.pixel` Pixel size is read from TIFF metadata. If unavailable, the app uses 1.19595 µm/pixel and displays a calibration warning. Verify this value before interpreting physical areas.

### Model & validation
`help.model.title` Model & validation
`help.model.intro` KidneyCyst segments the pronephros and measures its area. This version does not detect individual cysts or measure cyst features.
`help.model.model` Model: {model version}
`help.model.method` nnU-Net v2, trained in 2-D on 512 × 512 pixel patches for 250 epochs. Inference uses sliding windows and mirroring. The default prediction averages three models, each trained with one experimental run held out.
`help.model.input` Training image format: GFP-channel z-projections of zebrafish larvae at 2 days post-fertilisation, acquired on an Opera Phenix at 1080 × 1080 pixels and 1.196 µm/pixel. Preprocessing uses fixed intensity scaling without per-image normalisation.
`help.model.data` Training dataset: 686 images from three experimental runs (Runs 2–4), annotated in QuPath by Nikita Toločkovs (Institut Imagine). Blurred images, images without outlines and images with uncertain grades were excluded.
`help.model.area` Area is calculated from mask pixel count and pixel area, then divided by 1.02 to adjust for the reported difference between raster masks and QuPath polygon measurements.
`help.model.val.title` Validation
`help.model.val.intro` Leave-one-run-out cross-validation: each image was evaluated using a model trained without images from that experimental run. Predicted areas were compared with manual QuPath measurements (n = 686).
`help.model.val.table` [table: All / Run 2 / Run 3 / Run 4 / Cysts only × n, within 10%, within 20%, mean abs. error, ICC, Dice; numbers from KC009, not to be edited here]
`help.model.val.note` Baseline: assigning the same median area to every image gives an error within 20% for 81% of images. An independent blinded reader study comparing model-generated and manual outlines is in progress.
`help.model.lim.title` Limitations
`help.model.lim.1` All training annotations were produced by one annotator. Predictions may reflect that annotator’s boundary conventions.
`help.model.lim.2` Performance varies between experimental runs. For Run 3, 89% of area estimates were within 10% of the reference measurement.
`help.model.lim.3` Performance has not been evaluated on other developmental stages, microscopes, magnifications or reporter lines. Validate predictions before using measurements from these inputs.
`help.model.lim.4` Outlines that reach the image boundary are flagged. Their areas include only the region within the image.

### How to cite
`help.cite.title` How to cite
`help.cite.tbc` The software citation is provisional pending agreement on authorship. A release DOI is not yet available.
`help.cite.kidneycyst` Kukde A, et al. KidneyCyst: pronephros segmentation and area measurement in zebrafish larvae, version {version} [software]. 2026.
`help.cite.also` Please also cite the nnU-Net method:
`help.cite.nnunet` Isensee F, Jaeger PF, Kohl SAA, Petersen J, Maier-Hein KH. nnU-Net: a self-configuring method for deep learning-based biomedical image segmentation. Nature Methods 18, 203–211 (2021). doi:10.1038/s41592-020-01008-z
`help.cite.copy` Copy citations
`help.cite.copied` Copied.
`help.cite.methods` Report the KidneyCyst version, model version and review status of the measurements. Versions are recorded in run_settings.json and the report header; measurement provenance is recorded in the Area source column.

### Licenses & acknowledgments
`help.lic.title` Licenses & acknowledgments
`help.lic.code` Code license: MIT proposed; not yet approved. Release requires collaborator and institutional agreement and a dependency review.
`help.lic.weights` Model weights: redistribution terms have not been agreed.
`help.lic.example` Example image: provided by Institut Imagine. Redistribution terms have not been agreed.
`help.lic.qupath` Optional QuPath integration installs paquo (GPL-3.0) and JPype (Apache-2.0). QuPath (GPL-3.0) is installed separately if unavailable.
`help.lic.artwork` The zebrafish mascot was created with an AI image generator. Interface icons were created as vector artwork. Artwork licensing is documented separately from the application code.
`help.lic.funding.title` Funding
`help.lic.funding` Developed within the Cilia-AI Marie Skłodowska-Curie Actions Doctoral Network, Horizon Europe, grant agreement No 101169364. The formal funding acknowledgment is pending confirmation.
`help.lic.dev.title` Development
`help.lic.dev` Claude (Anthropic) was used for coding, debugging and documentation assistance.
`help.lic.tp.title` Third-party software
`help.lic.tp.intro` Third-party packages installed with KidneyCyst are listed below. License notices are provided in THIRD_PARTY_NOTICES.txt in the installation folder.
`help.lic.tp.cols` Package · Version · License

### Data & network
`help.net.title` Data & network
`help.net.1` Image analysis runs locally. The interface is served at 127.0.0.1 on this computer; KidneyCyst does not upload images, outlines or results.
`help.net.2` An internet connection is required during installation to download Python, PyTorch and dependencies. Optional QuPath integration downloads paquo and JPype and, if needed, QuPath from GitHub.
`help.net.3` The application does not perform update checks or send telemetry or crash reports. Model weights are bundled with the installation.
`help.net.4` Analysis results are saved in the _kidneycyst folder beside the input folder. Application logs are saved in the installation folder.

### Report a problem
`help.prob.title` Report a problem
`help.prob.intro` Contact aman.kukde@fht.org. Include:
`help.prob.1` Steps to reproduce the problem, the expected outcome and what happened. Attach a screenshot if useful.
`help.prob.2` kidneycyst_log.txt from the results folder, if available.
`help.prob.3` The diagnostic details below. Check logs and screenshots for information you do not want to share.
`help.prob.copy` Copy details
`help.prob.openlog` Open log folder
`help.prob.common.title` Common problems
`help.prob.c1` No TIFF images found: select a folder containing .tif or .tiff images. Subfolders are searched automatically.
`help.prob.c2` Slow processing: check the processing device on the home screen. CPU processing is slower. Fast mode reduces the number of models used for prediction.
`help.prob.c3` Excel table not updated: close results.xlsx in Excel. KidneyCyst retries writing it after the next review decision. Check the CSV export for the latest successfully saved results.
`help.prob.c4` Interface does not open: relaunch KidneyCyst from its application icon. The local server stops five minutes after the last application tab is closed.
`help.prob.diag` [details box: KidneyCyst version, Model, Computer, Python, PyTorch, nnU-Net, Processing on, Install folder, Results folder]

### About
`help.about.title` About
`help.about.name` KidneyCyst {version}
`help.about.versions` Model {model}. Python {v}, PyTorch {v}, nnU-Net {v}.
`help.about.app` Software development and model training: Aman Kukde, Human Technopole
`help.about.data` Data provision and annotation: Nikita Toločkovs and colleagues, Institut Imagine
`help.about.sup` Supervision: Alexandre Benmerah, Florian Jug
`help.about.funding` Funding: Cilia-AI MSCA Doctoral Network, grant agreement No 101169364
`help.about.tbc` Contributor roles are provisional pending collaborator confirmation.

---

## 4. Report page (report.html)

`rep.title` Kidney outline report
`rep.btn.back` Back to KidneyCyst *(only when opened from the app)*
`rep.btn.excel` Open Excel table *(only when opened from the app)*
`rep.btn.pdf` Download PDF
`rep.updated` Results changed. Updating…
`rep.source` Input: {folder} · Run: {date} · KidneyCyst {version} · Model {model}
`rep.n.images` images
`rep.n.withkidney` with an outline
`rep.n.checked` reviewed
`rep.n.flagged` flagged and unreviewed
`rep.n.median` µm² median area (includes {n} unreviewed outlines) / (all reviewed)
`rep.plate.title` Plate summary
`rep.plate.cols` Plate · Images · With outline · Reviewed · Median area (µm²) · Interquartile range (µm²)
`rep.plot.title.dots` Kidney area by image · One dot per image · Orange: unreviewed · Green: reviewed
`rep.plot.title.hist` Kidney area distribution
`rep.plot.few` Not enough outlines to display this chart.
`rep.filter.all` All
`rep.filter.look` Flagged
`rep.filter.todo` Unreviewed
`rep.filter.done` Reviewed
`rep.search` Search well, image or flag
`rep.shown` {n} shown
`rep.cols` Original · Outline · Image · Well · Field · Current area (µm²) · Area source · Model area (µm²) · Review decision · Flags
`rep.src.model` model
`rep.src.checked` reviewed
`rep.dec.auto` unreviewed
`rep.dec.accepted` ✓ outline accepted
`rep.dec.edited` ✓ outline corrected
`rep.dec.deleted` ✓ no kidney visible
`rep.dec.unusable` cannot assess
`rep.footer` Orange outlines are model-generated; blue outlines were manually corrected. Current area uses the reviewed outline when available, otherwise the model prediction. Images marked Cannot assess are excluded from area statistics. Measurements are exported to results.xlsx.
`rep.how.title` Analysis settings and provenance
`rep.how.rows` [rows, same as the Excel Settings sheet below]

---

## 5. Excel table (results.xlsx)

### Sheet "Results" (column names)
`xl.results.cols` Run · Plate · Well · Field · Current area (µm²) · Area source · Review decision · Model area (µm²) · Flags · Reviewed by · Reviewed at · Image file
`xl.decision.auto` unreviewed
`xl.decision.accepted` outline accepted
`xl.decision.edited` outline corrected
`xl.decision.deleted` no kidney visible
`xl.decision.unusable` cannot assess
`xl.areafrom.model` model
`xl.areafrom.checked` reviewed

### Sheet "Settings" (row names)
`xl.set.version` KidneyCyst version
`xl.set.model` Model
`xl.set.folds` Ensemble size — {n} models (folds {list})
`xl.set.date` Run date
`xl.set.input` Input folder
`xl.set.images` Images
`xl.set.cancelled` Run cancelled — yes / no
`xl.set.px` Pixel size — {px} µm ({n} images)
`xl.set.pxfrom` Calibration source — TIFF metadata / unverified default / manual entry
`xl.set.channel` GFP channel — channel {n} (first channel = 0)
`xl.set.scaling` Intensity scaling — (x - 163) / 13700, no clipping
`xl.set.prediction` Inference — sliding window (step 0.5); prediction averaging across mirrored inputs enabled
`xl.set.cleanup` Mask postprocessing — none
`xl.set.area` Area calculation — mask pixel count × pixel area ÷ 1.02
`xl.set.flags` Flag criteria — no GFP signal: …; atypical area: …; model uncertainty: …
`xl.set.device` Processing device — NVIDIA GPU / Apple GPU / CPU ({computer})
`xl.set.versions` Software versions
`xl.set.areafrom` Area source — model: unreviewed prediction; reviewed: outline accepted or corrected in KidneyCyst or QuPath. Images marked Cannot assess have no reported area.

### Sheet "Details"
`xl.details` (all technical columns, unchanged; for analysis scripts)

---

## 6. Flags (shown in the list, report and Excel)

`flag.nogfp` no GFP signal
`flag.nooutline` no outline found
`flag.edge` outline reaches image boundary
`flag.multi` multiple disconnected regions
`flag.area` atypical area for this plate
`flag.unsure` model uncertainty

---

## 7. Installer and start-up (Terminal / command window)

`inst.title` KidneyCyst installer
`inst.intro` Installation requires an internet connection. Keep this window open until installation finishes.
`inst.step1` Step 1 of 4: Creating a local Python environment…
`inst.step2` Step 2 of 4: Downloading and installing PyTorch…
`inst.step3` Step 3 of 4: Installing KidneyCyst and dependencies…
`inst.step4` Step 4 of 4: Running a sample-image test…
`inst.ok.python` ✓ Python ready
`inst.ok.torch` ✓ PyTorch ready
`inst.ok.kc` ✓ KidneyCyst installed
`inst.qupath.found` Optional integration: QuPath 0.6.0 found at {path}
`inst.qupath.none` QuPath is not installed. Built-in review is available.
`inst.box.pass` Sample-image test passed.
`inst.box.fail` Sample-image test failed. Send the error details to aman.kukde@fht.org.
`inst.box.sample` Sample area: {area} µm². Reference: {expected}.
`inst.box.device` Processing device: NVIDIA GPU / Apple GPU / CPU
`inst.done.mac` Installation complete. Open KidneyCyst from the desktop or Applications folder. You can close this window.
`inst.done.win` Installation complete. Open KidneyCyst from the desktop shortcut.
`inst.fail` Installation failed. Send the error details to aman.kukde@fht.org.
`inst.intel` Intel Macs are not supported by this build. An Apple Silicon Mac (M1 or later) is required.
`inst.close` Press any key to close.
`start.notinstalled` KidneyCyst is not installed. Starting installation…
`start.running` KidneyCyst is available at {address}. The server stops five minutes after the last application tab is closed.
`start.fail.mac` KidneyCyst could not start (error {n}). Send kidneycyst_app_log.txt from the installation folder to aman.kukde@fht.org.
`start.forbidden` Launch KidneyCyst using the application icon.

### Messages in the "Details" box while detection runs
`log.found` TIFF images found: {n}. Input: {folder}
`log.output` Output folder: {folder}
`log.loading` Loading model…
`log.heartbeat` Processing: {step}. Elapsed: {n} s.
`log.ready` Model loaded in {n} s. Device: {device}.
`log.finding` Processing {n} images. The first image may take longer.
`log.image` [{i}/{n}] {image}: {area} µm² ({n} s; estimated remaining: {t}) / no outline detected / {n} disconnected regions
`log.skipped` [{i}/{n}] {file}: skipped — {reason}
`log.cancelled` Detection cancelled. Results retained for {i} of {n} images.
`log.done` Processing complete: {n} images in {t} min. Flagged: {n}.
`log.files` Results table: {path} Report: {path}
`log.apple.fallback` Apple GPU processing failed: {error}. Continuing on CPU; processing may be slower.
`log.excel.locked` Could not update results.xlsx: {error}. Close the file in Excel. Writing will be retried at the next save.
`err.zstack` {file}: unsupported image shape {shape}. For a z-stack, create a 2-D maximum-intensity projection before import.
`err.singlechannel` {file}: cannot select channel {n} from a single-channel image.
`err.rerun` {folder} contains an existing QuPath project or reviewed results. A new run may overwrite them.
