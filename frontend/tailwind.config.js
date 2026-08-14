/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Source Sans 3',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Noto Sans SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
        serif: [
          'Noto Serif SC',
          'Source Han Serif SC',
          'Songti SC',
          'STSong',
          'SimSun',
          'serif',
        ],
      },
    },
  },
  plugins: [],
}
