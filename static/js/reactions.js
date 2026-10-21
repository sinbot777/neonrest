/* One handler for shared post controls in profiles, feeds and private Circles. */
(() => {
  const pending = new Set();
  document.addEventListener('click', async event => {
    const button = event.target.closest('.react-btn[data-reaction-url]');
    if (!button || button.disabled) return;
    const box = button.closest('.react-form');
    if (!box) return;
    event.preventDefault();
    const emoji = button.dataset.emoji;
    const postId = button.dataset.postId;
    const key = JSON.stringify([postId, emoji]);
    if (pending.has(key)) return;
    pending.add(key);
    button.disabled = true;
    const status = box.querySelector('.reaction-status');
    if (status) status.textContent = '';
    try {
      const response = await fetch(button.dataset.reactionUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': box.dataset.csrfToken},
        body: JSON.stringify({emoji})
      });
      if (!response.ok) {const failure=await response.json().catch(()=>null);throw new Error(failure?.message || 'Could not save the reaction. Check the page before trying again.');}
      const data = await response.json();
      if (data.status !== 'ok') throw new Error('Reaction was not saved');
      document.querySelectorAll('.react-btn[data-reaction-url]').forEach(other => {
        if (other.dataset.postId !== postId || other.dataset.emoji !== emoji) return;
        const added = data.action === 'added';
        other.classList.toggle('active', added);
        other.setAttribute('aria-pressed', String(added));
        other.textContent = emoji;
        if (data.count > 0) {
          const count = document.createElement('sub');
          count.textContent = String(data.count);
          other.append(count);
        }
      });
    } catch (error) {
      if (status) status.textContent = error.message || 'Could not save the reaction. Check the page before trying again.';
    } finally {
      button.disabled = false;
      pending.delete(key);
    }
  });
})();
