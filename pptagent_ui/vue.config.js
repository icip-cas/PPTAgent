const { defineConfig } = require('@vue/cli-service')

module.exports = defineConfig({
  transpileDependencies: true,
  devServer: {
    proxy: {
      '/api': {
        target: 'http://localhost:9297',
        changeOrigin: true
      },
      '/wsapi': {
        target: 'ws://localhost:9297',
        ws: true,
        changeOrigin: true,
      },
    },
    port: 8088
  },
  css: {
    loaderOptions: {
      postcss: { postcssOptions: { config: false } }
    }
  }
})
