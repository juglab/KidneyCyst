# KidneyCyst: how to use it

KidneyCyst finds the kidney (pronephros) in your GFP images, measures its area, and lets you check and fix
every outline in a simple review screen. No programming needed, and no other program is required.

## Install (once, about 10 minutes, needs internet)

Download the zip for your computer: **KidneyCyst-Mac.zip** (Apple Silicon, M1 or later), **KidneyCyst-Windows.zip**
or **KidneyCyst-Linux.zip**. Unzip it into **Documents**. The folder contains two things:

| File | What to do |
|---|---|
| **Install KidneyCyst** | Double-click it once. Mac: the first time, right-click it, choose **Open**, then **Open**. Windows: if you see *"Windows protected your PC"*, click **More info**, then **Run anyway**. |
| **Read me** | This guide. |

The installer shows four steps, then a green box (**Sample-image test passed**). It creates a **KidneyCyst** app with
its icon (Mac: in Applications and on the Desktop; Windows: on the desktop and in the Start menu) and opens it.

- **Graphics card:** used automatically if there is one (NVIDIA on Windows/Linux, the Apple GPU on Macs).
- **No graphics card:** it still works, just slower.

## Use it

Open **KidneyCyst** like any other app. It opens as a page in your web browser.

**Start page.** **New analysis** (choose the folder with your TIFF images, for example one plate) and the list of **Your runs**:
every plate you have analysed, with its status (*Detected*, *In review*, *Final*). Click **Open** to go back to one.

**Run page.** Each run has its own page: its name at the top (click to rename), then three steps:

| Step | What you do |
|---|---|
| **1. Detect** | Click **Run detection** and wait for the bar to fill. **With a graphics card:** seconds per image. **Without one:** a few minutes per image (*Fast mode* is 3× faster). |
| **2. Review** | Check the outlines one image at a time (see below). |
| **3. Results** | **Open report**: an overview page. **Open Excel table**: areas and your decisions. |

Your images are never changed. The results go into a new folder next to them, named `<your folder>_kidneycyst`.

## The review screen

| Press | Meaning |
|---|---|
| **A** (or Enter) | The outline is right. If you fixed it, this saves your fix. Then it moves to the next image. |
| **N** | There is no kidney in this image. |
| **U** | Undo the decision you just saved (or click *Undo* in the message). |
| **→ / ←** | Next / previous image, without deciding. |
| Drag with the mouse | Paint the outline bigger. |
| Right-drag, or **Shift**-drag | Erase. **E** switches between paint and erase; **[** and **]** change the brush size. |
| **Z** / **R** | Undo the last stroke / go back to the computer's outline. |
| **F** / **H** | Whole image or zoom / hide the outline to see the bare image. |

**Grade and elbow length (beta).** The panel on the right also shows the model's grade (normal / unfused / cyst, with
its probability) and two elbow-to-elbow lengths. They are **beta: not yet checked against manual grading**. To record
your own values: choose **Your grade** from the list, and press **M** (*Measure elbow*), click points along the tubule
from one elbow to the other, then double-click or press **Enter**. **Esc** or **Z** removes the last point; **Clear**
removes the measurement. **J** shows or hides the elbow lines (dashed orange: the model's; blue: yours). Your values go
into the Excel table with your name and the time, and they are kept if detection is run again.

- Images that need a look come first; choose *not reviewed*, *flagged* or *all* at the top.
- Every decision is saved straight away. You can stop at any time and continue later, even on another day.
- The table gets one row per image with your decision (`status`), the area (`reviewed_area_um2`), your name and the time.
  Your fixed outlines are also kept to improve the model.

**QuPath (optional):** if you prefer QuPath, click **Open in QuPath**. It opens with the current outlines. After you save
in QuPath, click **Read back QuPath changes**. QuPath edits and review-screen decisions end up in the same table.

## Using a more powerful computer (optional)

If your own computer has no graphics card but you can log in to one that has (a GPU workstation or a cluster), detection
can run there while everything else stays on your computer. On the run page, click **Change where detection runs**, choose **Another computer, over SSH**, enter its name (as you would type after `ssh`) and click **Test connection**.

- The other computer needs a login without a password (an SSH key). If the test says the password is refused, click
  **Set up key login…** and type your password once.
- KidneyCyst is found there automatically (usual install places, your home folder, conda environments). If it is not
  installed, click **Install KidneyCyst there**: the app copies its program and model into a new folder
  `~/KidneyCyst-remote` and downloads Python and PyTorch there (about 10 minutes, 8 GB). Your settings and the command
  that worked are kept in `~/.kidneycyst` on your computer, so reinstalling KidneyCyst does not lose them.
- **Clusters with a job queue (Slurm)** are recognised automatically: detection is submitted as a GPU job, the page
  shows *Waiting for a GPU…* while it is queued, then the usual progress. The job options (partition, time limit) are
  pre-filled and can be changed.
- The images are copied there for the run and deleted afterwards. If the other computer cannot be reached, KidneyCyst
  offers to run on your own computer instead.

## Good to know

- **The area** is measured the same way as in your Excel sheets: the area QuPath shows for the outline.
- **Pixel size** is read from the TIFF. If it is missing, 1.19595 µm/px is used. It is always recorded.
- **A flag** is a reason to look, not an error:

| Flag | Meaning |
|---|---|
| no GFP signal | the image looks empty |
| no kidney found | nothing was drawn |
| touches border | the kidney may be cut off |
| >1 piece | the outline is in several parts |
| area unusual | very different from the rest of the plate |
| low confidence | the model was unsure |

- **Re-running a folder** starts fresh. Your earlier decisions are not deleted: they move into a folder named `replaced_…`.
- **New kinds of images:** the model learned from Runs 2–4 (2 dpf, GFP). On other stages or microscopes, check more images.
- **Problems:** send a screenshot, plus the file `kidneycyst_log.txt` from the results folder, to Aman Kukde (Jug lab).

---
*For Aman / server use:* `ssh hpc sbatch /home/aman.kukde/KidneyCyst/slurm/run_folder.sbatch <folder> --qupath`;
command line: `kidneycyst run|sync|open|qupath build` (see `kidneycyst --help`); window: `python -m kidneycyst.gui`.
