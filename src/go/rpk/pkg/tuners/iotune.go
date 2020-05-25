package tuners

import (
	"fmt"
	"time"
	"vectorized/pkg/os"
	"vectorized/pkg/tuners/iotune"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/afero"
)

func NewIoTuneTuner(
	fs afero.Fs,
	evalDirectories []string,
	ioConfigFile string,
	duration, timeout time.Duration,
) Tunable {
	return NewCheckedTunable(
		NewIOConfigFileExistanceChecker(fs, ioConfigFile),
		func() TuneResult {
			return tune(evalDirectories, ioConfigFile, duration, timeout)
		},
		func() (bool, string) {
			return checkIfIoTuneIsSupported(fs)
		},
		false)
}

func checkIfIoTuneIsSupported(fs afero.Fs) (bool, string) {
	if exists, _ := afero.Exists(fs, iotune.Bin); !exists {
		return false, fmt.Sprintf("'%s' not found in PATH", iotune.Bin)
	}
	return true, ""
}

func tune(
	evalDirectories []string,
	ioConfigFile string,
	duration, timeout time.Duration,
) TuneResult {
	ioTune := iotune.NewIoTune(os.NewProc(), timeout)
	args := iotune.IoTuneArgs{
		Dirs:           evalDirectories,
		Format:         iotune.Seastar,
		PropertiesFile: ioConfigFile,
		Duration:       duration,
		FsCheck:        false,
	}
	output, err := ioTune.Run(args)
	for _, outLine := range output {
		log.Debug(outLine)
	}
	if err != nil {
		return NewTuneError(err)
	}
	return NewTuneResult(false)
}
