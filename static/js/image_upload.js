const MiB = 1024 * 1024;
const MAX_SOURCE = 25 * MiB;
const MAX_UPLOAD = 5 * MiB;
const blobFromCanvas = (canvas, type, quality) => new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not prepare that photo.')), type, quality));

export async function preparePostImage(file) {
  if (file.size > MAX_SOURCE) throw new Error('Choose an image smaller than 25 MB.');
  const bytes = new Uint8Array(await file.slice(0, 65536).arrayBuffer());
  const signature = String.fromCharCode(...bytes.slice(0, 12));
  if (signature.startsWith('GIF8')) {
    if (file.size > MAX_UPLOAD) throw new Error('Animated GIFs must be 5 MB or smaller.');
    return file;
  }
  const isPNG = bytes[0] === 137 && signature.slice(1, 4) === 'PNG';
  const isWebP = signature.startsWith('RIFF') && signature.slice(8, 12) === 'WEBP';
  const isJPEG = bytes[0] === 255 && bytes[1] === 216;
  if (!isPNG && !isWebP && !isJPEG) throw new Error('Choose a JPG, PNG, WebP or GIF image. If your phone uses HEIC, export it as JPG first.');
  // Do not flatten animation-bearing PNG or WebP files in the browser.
  if (isWebP && bytes[12] === 86 && bytes[13] === 80 && bytes[14] === 56 && bytes[15] === 88 && (bytes[20] & 2)) {
    throw new Error('For animated images, use GIF so the animation is preserved.');
  }
  if (isPNG) {
    for (let pos = 8; pos + 12 <= bytes.length;) {
      const size = new DataView(bytes.buffer).getUint32(pos);
      const chunk = String.fromCharCode(...bytes.slice(pos + 4, pos + 8));
      if (chunk === 'acTL') throw new Error('For animated images, use GIF so the animation is preserved.');
      if (chunk === 'IDAT') break;
      pos += size + 12;
    }
  }
  const url = URL.createObjectURL(file);
  const image = new Image();
  try {
    image.src = url;
    await image.decode();
    if (image.naturalWidth * image.naturalHeight > 80_000_000) throw new Error('Choose a photo under 80 megapixels.');
    if (file.size <= MiB && Math.max(image.naturalWidth, image.naturalHeight) <= 2200) return file;
    const canvas = document.createElement('canvas');
    const ratio = Math.min(1, 2200 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('This browser could not prepare the image.');
    context.imageSmoothingQuality = 'high';
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    let blob = await blobFromCanvas(canvas, 'image/webp', .92);
    if (blob.type !== 'image/webp') blob = await blobFromCanvas(canvas, isJPEG ? 'image/jpeg' : 'image/png', .9);
    if (blob.size > 2 * MiB && blob.type !== 'image/png') blob = await blobFromCanvas(canvas, blob.type, .84);
    if (blob.size > MAX_UPLOAD) throw new Error('That image is still too large. Try a smaller copy.');
    const suffix = blob.type === 'image/webp' ? 'webp' : blob.type === 'image/png' ? 'png' : 'jpg';
    return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.' + suffix, {type: blob.type, lastModified: file.lastModified});
  } catch (error) {
    throw new Error(error.message || 'Could not read that photo. Try exporting it as JPG.');
  } finally { URL.revokeObjectURL(url); }
}

const ready = new WeakSet();
const busy = new WeakSet();
document.addEventListener('submit', async event => {
  const form = event.target;
  const input = form.querySelector('input[type=file][name=post_image]');
  if (!input || !input.files.length || ready.has(form)) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (busy.has(form)) return;
  busy.add(form);
  const submitter = event.submitter;
  let status = form.querySelector('.image-upload-status');
  if (!status) {
    status = document.createElement('p'); status.className = 'image-upload-status';
    status.setAttribute('role', 'status'); input.closest('label')?.after(status);
    if (!status.isConnected) input.after(status);
  }
  status.textContent = 'Preparing your image…';
  try {
    const original = input.files[0];
    const prepared = await preparePostImage(original);
    if (input.files[0] !== original) throw new Error('The image selection changed. Please press Post again.');
    const files = new DataTransfer(); files.items.add(prepared); input.files = files.files;
    status.textContent = prepared === original ? 'Image ready.' : `Image ready: ${(original.size / MiB).toFixed(1)} MB → ${(prepared.size / MiB).toFixed(2)} MB.`;
    ready.add(form);
    try { form.requestSubmit(submitter || undefined); } finally { ready.delete(form); }
  } catch (error) {status.textContent = error.message; status.setAttribute('role','alert');}
  finally {busy.delete(form);}
}, true);
