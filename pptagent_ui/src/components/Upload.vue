<template>
  <!-- Upload form -->
  <div class="upload-container">
    <div class="upload-options">
      <!-- Row 1: Upload Buttons -->
      <div class="upload-buttons">
        <div class="upload-section">
          <label for="pptx-upload" class="upload-label">
            Upload PPTX
            <span v-if="pptxFile" class="uploaded-symbol">✔️</span>
          </label>
          <input type="file" id="pptx-upload" @change="handleFileUpload($event, 'pptx')" accept=".pptx" />
        </div>
        <div class="upload-section">
          <label for="pdf-upload" class="upload-label">
            Upload PDF
            <span v-if="pdfFile" class="uploaded-symbol">✔️</span>
          </label>
          <input type="file" id="pdf-upload" @change="handleFileUpload($event, 'pdf')" accept=".pdf" />
        </div>
      </div>

      <!-- Row 2: Selectors -->
      <div class="selectors">
        <div class="pages-selection">
          <select v-model="selectedPages">
            <option v-for="page in pagesOptions" :key="page" :value="page">{{ page }} 页</option>
          </select>
        </div>
      </div>

      <!-- Row 3: Button -->
      <button @click="goToGenerate" class="next-button">Next</button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'UploadComponent',
  data() {
    return {
      pptxFile: null,
      pdfFile: null,
      selectedPages: 6,
      pagesOptions: Array.from({ length: 12 }, (_, i) => i + 3),
      isPptxEnabled:true
    }
  },
  methods: {
    handleFileUpload(event, fileType) {
      console.log("file uploaded :", fileType)
      const file = event.target.files[0]
      if (fileType === 'pptx') {
        this.pptxFile = file
      } else if (fileType === 'pdf') {
        this.pdfFile = file
      }
    },
    async goToGenerate() {
      this.$axios.get('/')
        .then(response => {
          console.log("Backend is running", response.data);
        })
        .catch(error => {
          console.error(error);
          alert('Backend is not running or too busy, your task will not be processed');
          return;
        });

      if (!this.pdfFile) {
        alert('Please upload a PDF file.');
        return;
      }

      const formData = new FormData();
      if (this.pptxFile) {
        formData.append('pptxFile', this.pptxFile);
      }
      formData.append('pdfFile', this.pdfFile);
      formData.append('numberOfPages', this.selectedPages);

      try {
        const uploadResponse = await this.$axios.post('/api/upload', formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        })
        const taskId = uploadResponse.data.task_id
        console.log("Task ID:", taskId)
        // Navigate to Generate component with taskId
        this.$router.push({ name: 'Generate', state: { taskId: taskId } })
      } catch (error) {
        console.error("Upload error:", error)
        this.statusMessage = 'Failed to upload files.'
      }
    }
  }
}
</script>

<style scoped>
.upload-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  background-color: #f0f8ff;
  padding: 40px;
  box-sizing: border-box;
}

.upload-options {
  display: flex;
  flex-direction: column;
  gap: 30px;
  width: 100%;
  max-width: 80%;
}

.upload-buttons,
.selectors {
  display: flex;
  justify-content: center;
  gap: 20px;
  width: 100%;
}

.upload-section,
.pages-selection {
  flex: 0 1 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 10px;
}

.upload-section {
  margin-left: 3em;
  margin-right: 3em;
}

.pages-selection {
  margin-left: 3em;
  margin-right: 3em;
}

.upload-label {
  position: relative;
  background-color: #42b983;
  color: white;
  padding: 10px 20px;
  border-radius: 5px;
  cursor: pointer;
  width: 100%;
  text-align: center;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.3s;
  font-size: 16px;
}

.upload-label:hover {
  background-color: #369870;
}

.upload-section input[type="file"] {
  display: none;
}

.pages-selection select {
  padding: 10px;
  border-radius: 5px;
  border: 1px solid #ccc;
  width: 100%;
  height: 40px;
  box-sizing: border-box;
  font-size: 16px;
}

.next-button {
  background-color: #35495e;
  color: white;
  padding: 12px 0;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  width: 220px;
  display: block;
  margin: 30px auto 0;
  font-size: 20px;
  font-weight: 700;
  transition: background-color 0.3s, transform 0.2s;
}

.next-button:hover {
  background-color: #2c3e50;
  transform: scale(1.05);
}

.uploaded-symbol {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: green;
  font-size: 18px;
}

@media (max-width: 600px) {

  .upload-buttons,
  .selectors {
    flex-direction: column;
    gap: 35px;
  }

  .next-button {
    width: 100%;
  }
}

.or-divider {
  display: flex;
  align-items: center;
  color: #666;
  font-weight: bold;
  font-size: 14px;
  margin: 0 -10px;
}

@media (max-width: 600px) {
  .or-divider {
    margin: -15px 0;
    justify-content: center;
  }
}
</style>
