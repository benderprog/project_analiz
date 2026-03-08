(function () {
  const dropZone = document.querySelector('.drop-zone');
  const fileInput = document.getElementById('id_file');
  const filesHint = document.getElementById('selected-files-hint');

  if (!dropZone || !fileInput) return;

  const updateSelectedFilesHint = () => {
    if (!filesHint) return;
    const count = fileInput.files ? fileInput.files.length : 0;
    filesHint.textContent = `Выбрано файлов: ${count}`;
  };

  const toggleHighlight = (on) => {
    dropZone.classList.toggle('is-dragover', on);
  };

  const block = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  ['dragenter', 'dragover'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      block(event);
      toggleHighlight(true);
    });
  });

  ['dragleave', 'drop'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      block(event);
      toggleHighlight(false);
    });
  });

  fileInput.addEventListener('change', updateSelectedFilesHint);

  dropZone.addEventListener('drop', (event) => {
    const droppedFiles = event.dataTransfer ? event.dataTransfer.files : null;
    if (!droppedFiles || droppedFiles.length === 0) return;

    try {
      const transfer = new DataTransfer();
      Array.from(droppedFiles).forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
    } catch (_error) {
      fileInput.files = droppedFiles;
    }

    updateSelectedFilesHint();
  });

  updateSelectedFilesHint();
})();
